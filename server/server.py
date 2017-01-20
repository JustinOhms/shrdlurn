"""
SHRDLURN - Community & Logging Server

## Data Formats

We store the logs in the "DATA_FOLDER/log" path. Every user gets a file named
with their "SESSION_ID.json". Every log is composed of lines of json objects that
correspond to logged events. We append new logs to the end of every file as we
receive them.

We store the structs in the "DATA_FOLDER/structs" path. Structs are then stored
in an interior folder whose name is the SESSION_ID
of the user who submitted the struct. Within that user's folder, we store each
struct in its own file. Every struct file has as its first line a JSON array
corresponding to a list of the users who upvoted that struct. The second line
is the timestamp of when the struct was submitted. And the third line is a JSON
object of the submitted struct.

## API

server.py provides an API for the client to log actions, share structures, and
view the community's work.

A client can make the following socket requests:

    - "session": {"sessionId": SESSION_ID}
        on first connection, the client should submit a sessionId to
        be used to match all future requests. This sessionId is stored in the
        flask "request" global context variable.
    - "log": {"type": LOG_TYPE, "msg": OBJECT}
        whenever the client would like an event logged, the client can submit a
        log query and this will be logged in a file with the SESSION_ID as the
        filename.
    - "upvote": {"uid": UID, "id": ID}
        a user can upvote another user's struct by passing in the struct's
        uid (the scrub_uid() of the user who submitted it) and the id of
        the struct itself.
    - "share": {"struct": STRUCT}
        a user can share a struct and it will be saved to their directory


The server expects the client to handle the following messages when connected
to the "community" room:

    - "new_accept": {"uid": UID, "query": QUERY, "timestamp": TIMESTAMP}
        whenever a connected user accepts a new structure, we broadcast it
    - "new_define": {"uid": UID, "defined": DEFINED_TERM, "timestamp": TIMESTAMP}
        whenever a connected user defines a new query, we broadcast it
    - "upvote": {"uid": UID, "id": ID, "up": UPVOTER_ID, "score": NEW_SCORE}
        whenever a user upvotes a new struct, we broadcast the scrubbed uid
        of the new user
    - "struct": {"uid": session.uid, "id": new_struct_id, "score": score, "upvotes": [], "struct": STRUCT}
        emitted when either a new struct has been shared or on an initial load,
        when reading all the structs - this gets emitted one by one.
    - "utterances": {"uid": UID, "utterances": [UTTERANCES]}
        when a user joins the community room, we emit the latest 5 turkers'
        last 11 utterances.
"""


import json
import sys
import time
import os
import random
import eventlet
import glob
from flask import Flask, request, session
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room

# Setup flask
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)

# We need to enable CORS support to handle CORS flights from the frontend
CORS(app)

# The community server runs through websockets to enable real-time updates
socketio = SocketIO(app)

# Hardcoded folders for the data (mirrored in data_rotate.py)
DATA_FOLDER = "data/"
LOG_FOLDER = os.path.join(DATA_FOLDER, "log/")
STRUCTS_FOLDER = os.path.join(DATA_FOLDER, "structs/")

# Scoring function parameters
GRAVITY = 1.4  # higher the gravity, the faster old structs lose score
TIME_INTERVAL = 1800.0  # break off by every 30 minutes


@app.route("/")
def index():
    return "Hello World! ~ SHRDLURN Community Server"


def score_struct(timestamp, upvotesN):
    """We use the HN formula to score structures for ranking.

    Formula is: (P + 1) / ((T + 2)^GRAVITY)
    where: - P: the number of unique upvotes for the structure
           - T: the amount of TIME_INTERVALs that have elapsed since the
             structure was submitted
           - GRAVITY: a constant to determine the weight of T v. P
    """
    time_ago = (current_unix_time() / TIME_INTERVAL) - (int(timestamp) / TIME_INTERVAL)
    return (upvotesN + 1) / ((time_ago + 2) ** GRAVITY)


def current_unix_time():
    """Returns the number of seconds since the epoch."""
    return int(time.time())


def scrub_uid(uid):
    """We don't want to reveal other users' full session_id's to other users,
    so we hide it by just sending the first 8 characters.

    NB: We use the session_id as the sole source of truth for authentication
    and logging purposes - if it was leaked, other turkers would be able to
    impersonate users.

    TODO: Convert to using signed JWTs.
    """
    return uid[:8]


def emit_structs():
    """Walk through the STRUCTS_FOLDER directory and read each struct and emit
    it to the user one by one."""

    for uid in [name for name in os.listdir(STRUCTS_FOLDER) if os.path.isdir(os.path.join(STRUCTS_FOLDER, name))]:
        uid_folder = os.path.join(STRUCTS_FOLDER, uid)
        for fname in os.listdir(uid_folder):
            path = os.path.join(uid_folder, fname)

            with open(path, 'r') as f:
                lines = f.readlines()
                if (len(lines) != 3):
                    continue

                upvotes = json.loads(lines[0].strip())
                timestamp = json.loads(lines[1].strip())
                struct = json.loads(lines[2].strip())

                score = score_struct(timestamp, len(upvotes))
                message = {"uid": scrub_uid(uid), "id": fname[:-5], "score": score, "upvotes": upvotes, "struct": struct}
                emit("struct", message)


def emit_utterances():
    """Emit a list of the last 11 utterances for the 5 most recent turkers."""
    latest_5 = []
    for dirname, subdirs, files in os.walk(LOG_FOLDER):
        for fname in files:
            path = os.path.join(dirname, fname)

            mtime = os.stat(path).st_mtime
            file_info = (mtime, fname[:-5], path)

            if len(latest_5) < 5:
                latest_5.append(file_info)
            else:
                earliest_time = latest_5[0][0]
                earliest_idx = 0
                for idx, l in enumerate(latest_5):
                    if l[0] < earliest_time:
                        earliest_time = l[0]
                        earliest_idx = idx

                if mtime > earliest_time:
                    latest_5[earliest_idx] = file_info

    for (time, uid, path) in sorted(latest_5, key=lambda s: int(s[0]), reverse=True):
        uid = scrub_uid(uid)
        utts = []
        count = 0
        for line in reverse_readline(path):
            data = json.loads(line)
            if (data["type"] == "accept" or data["type"] == "define"):
                utts.append(line)
                count += 1

            if count > 10:
                break

        message = {"uid": uid, "utterances": utts}
        emit("utterances", message)


def log(message):
    """Logs the given message by writing it in the uid's JSON log file."""
    path = os.path.join(LOG_FOLDER, session.uid + ".json")

    # Add a timestamp to the log
    message["timestamp"] = current_unix_time()

    # Append the log to the end of the file
    with open(path, 'a') as f:
        json.dump(message, f)
        f.write('\n')


@socketio.on('join')
def on_join(data):
    """When a user joins the "community" room, emit to them the list of
    the top 5 most recent users' most recent 11 utterances and all of the
    submitted structs."""

    room = data['room']
    join_room(room)

    if (room == "community"):
        # We iterate through all the shared structs and emit them one by one
        emit_structs()

        # And then we emit the most recent 5 users' utterances per file
        emit_utterances()


@socketio.on('leave')
def on_leave(data):
    """A user can leave a room"""
    username = data['sessionId']
    room = data['room']
    leave_room(room)


@socketio.on('share')
def handle_share(data):
    """Users can share structs. We save this struct in STRUCTS_FOLDER/UID/SCORE_ID.json

    where UID is the uid of the user who submitted the struct, SCORE is the
    current score of the struct and ID is the unique index (auto-incremented) of
    this particular struct.."""

    user_structs_folder = os.path.join(STRUCTS_FOLDER, session.uid)
    make_dir_if_necessary(user_structs_folder)
    names = os.listdir(user_structs_folder)
    new_struct_id = "1"
    if len(names) > 0:
        new_struct_id = str(max([int(name[:-5]) for name in names]) + 1)

    new_struct_path = os.path.join(user_structs_folder, new_struct_id + ".json")

    submission_time = current_unix_time()
    score = score_struct(submission_time, 0)

    with open(new_struct_path, 'w') as f:
        f.write("[]\n")  # it starts with no upvoters
        f.write(str(submission_time) + "\n")  # timestamp of submission
        f.write(json.dumps(data["struct"]))  # the actual struct

    # Broadcast addition to the "community" room
    message = {"uid": scrub_uid(session.uid), "id": new_struct_id, "score": score, "upvotes": [], "struct": data["struct"]}
    emit("struct", message, broadcast=True, room="community")


@socketio.on('upvote')
def upvote(data):
    """Users can upvote other users' structures.

    Data should consist of: {"uid": UID, "id": "ID"}"""

    # if no session.uid, do nothing
    if not session.uid:
        return

    user_structs_folder = os.path.join(STRUCTS_FOLDER, data["uid"])
    struct_path = os.path.join(STRUCTS_FOLDER, data["uid"], data["id"] + ".json")

    # if the struct does not exist, do nothing
    if not os.path.isfile(struct_path):
        return

    # Read the first line of the file to get the number of upvotes
    upvotes = []
    score = 0
    with open(struct_path, 'r') as f:
        upvotes = json.loads(f.readline().strip())

        # If the user has not already upvoted this, add them
        if session.uid not in upvotes:
            upvotes.append(session.uid)

            with open(struct_path, 'w') as fw:
                fw.write(json.dumps(upvotes) + "\n")
                timestamp = f.readline()
                fw.write(timestamp)  # rewrite the timestamp
                fw.write(f.readline())  # rewrite the actual struct

    score = score_struct(timestamp, len(upvotes))

    # and then broadcast the new upvote to the room:
    message = {"uid": data["uid"], "id": data["id"], "up": scrub_uid(session.uid), "score": score}
    emit("upvote", message, broadcast=True, room="community")


@socketio.on('log')
def handle_log(data):
    """Receive a log message in the form of {"type": LOG_TYPE, "msg": LOG_OBJECT}

    If the log type is an accept of utterance, then broadcast that to all
    community-connected clients."""

    if "type" not in data:
        # If the log object is improper, don't do anything.
        return

    log(data)

    # If the message is an accept or define type, broadcast it to all
    # community-connected clients so they can update their display.
    if data["type"] == "accept":
        emit("new_accept", {"uid": scrub_uid(session.uid), "query": data["msg"]["query"], "timestamp": current_unix_time()},
             broadcast=True, room="community")
    elif data["type"] == "define":
        emit("new_define", {"uid": scrub_uid(session.uid), "defined": data["msg"]["defineAs"], "timestamp": current_unix_time()},
             broadcast=True, room="community")


@socketio.on('session')
def session(data):
    """On every new connection, the client should transmit the sessionId to tell
    the server that a new session has started. This sessionId is then used for
    all future authentication by storing it as uid in the session global
    context variable."""
    session.uid = data['sessionId']
    log({"type": "connect"})


@socketio.on('connect')
def connect():
    """Return an ok if connection worked"""
    emit('ok', {'data': 'Connected'})


@socketio.on('disconnect')
def disconnect():
    """Log the fact that a user disconnected."""
    log({"sessionId": session.uid, "type": "disconnect"})


# http://stackoverflow.com/questions/2301789/read-a-file-in-reverse-order-using-python
def reverse_readline(filename, buf_size=8192):
    """a generator that returns the lines of a file in reverse order"""
    with open(filename) as fh:
        segment = None
        offset = 0
        fh.seek(0, os.SEEK_END)
        file_size = remaining_size = fh.tell()
        while remaining_size > 0:
            offset = min(file_size, offset + buf_size)
            fh.seek(file_size - offset)
            buffer = fh.read(min(remaining_size, buf_size))
            remaining_size -= buf_size
            lines = buffer.split('\n')
            # the first line of the buffer is probably not a complete line so
            # we'll save it and append it to the last line of the next buffer
            # we read
            if segment is not None:
                # if the previous chunk starts right from the beginning of line
                # do not concact the segment to the last line of new chunk
                # instead, yield the segment first
                if buffer[-1] is not '\n':
                    lines[-1] += segment
                else:
                    yield segment
            segment = lines[0]
            for index in range(len(lines) - 1, 0, -1):
                if len(lines[index]):
                    yield lines[index]
        # Don't yield None if the file was empty
        if segment is not None:
            yield segment


def make_dir_if_necessary(dir_name):
    """Creates the directory if not already created"""
    if not os.path.exists(dir_name):
        os.makedirs(dir_name)


if __name__ == "__main__":
    # Create any missing directories
    make_dir_if_necessary(DATA_FOLDER)
    make_dir_if_necessary(LOG_FOLDER)
    make_dir_if_necessary(STRUCTS_FOLDER)

    # Run the server
    # NB: socketio.run uses eventlet to run a production webserver
    # so, make sure that "eventlet" is installed, or else it will default to
    # the werkzeug development server which is unsafe and slow.
    socketio.run(app, host='0.0.0.0', port=8406)
