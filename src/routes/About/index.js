import React, { Component } from "react"
import { connect } from "react-redux"
import Actions from "actions/logger"
import { Link } from "react-router"
import "./styles.css"
import { TUTORIAL_URL, SLACK_SIGNUP_URL, DOCUMENTATION_URL } from "constants/strings"

import CubesImage from "images/struct_frames_cubes.png"

class Information extends Component {
	componentDidMount() {
		this.props.dispatch(Actions.joinCommunity())
	}

	render() {
		const height = "150px";
		return (
			<div className="About">
				<div>

					<img src={CubesImage} alt="example voxel structure" height={height} />
					<p>Voxelurn is a command interface for building {' '}
						<Link to={{ pathname: "/community", query: this.props.query }} activeClassName="active" target="_blank">voxel structures</Link>.{' '}
						It is an experimental platform for developing technologies
				allowing computers to understand a naturalized programming language, which allows people to access
				to the power of programming languages
				without conforming to their uncompromising syntax.{' '}
						Voxlurn does this by learning from its user community interactively starting from just a normal programming language.
				</p>
        <h2>Get started</h2>
        Go to the <Link to="/build">build page</Link> and type "repeat 3 [add red top]".
      Voxelurn always understands the core language which has a fixed syntax like other programming languages.
      However, you might want more flexibility and many alternative ways of saying the same thing.
      In Voxelurn, you can define
      "add red top 3 times" as "repeat 3 [add red top]" and in the future you can try
      "add green left 5 times".
					{/*
					<div className="Examples">
					<img src={require('./examples.png')} height={height}/>
				<img src={require('./struct_monster_inc.png')} height={height}/>
				<img src={require('./struct_frames_cubes.png')} height={height}/>
				<img src={require('./struct_venison.png')} height={height}/>
				</div>
				*/}
					<h2>Prizes</h2>
					<p>
						We award prizes for users contributing the most useful language, and users building the best structures.
				Six $50 prizes are handed out every two weeks for the top 3 language teachers and the top 3 best structures.
				To participate, you have to <a target="_blank" href="https://shrdlurn.signup.team/">join</a> our <a target="_blank" href="https://shrdlurn.slack.com/">slack channel</a> and login.
				More details on the competition can be found there.
				</p>



				<h2>Learn more</h2>
        <div><a target="_blank" href={DOCUMENTATION_URL}>Documentation</a>: core language, the setup, etc </div>
        <div><a target="_blank" href={TUTORIAL_URL}>Video tutorial</a>: see the system at work</div>
        <a target="_blank" href={SLACK_SIGNUP_URL}> Slack</a> (<a target="_blank" href="https://shrdlurn.signup.team/">signup</a>): signup and join to submit more structures and win prizes
        <p>
        Even more information can be found on <a href="https://github.com/sidaw/shrdlurn">github</a>.
        </p>
      </div>
			</div>
		)
	}
}

const mapStateToProps = (state) => ({
	structs: state.logger.structs,
	utterances: state.logger.utterances,
	topBuilders: state.logger.topBuilders
})

export default connect(mapStateToProps)(Information)
