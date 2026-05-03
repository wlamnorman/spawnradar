# Catalog Game Definitions

Internal game definitions for pre-populating the creator database.
These are NOT customer games — they're seed definitions that ensure
the creator index has broad coverage across major genre spaces before
real customers sign up.

Each JSON file follows the same schema as sandbox experiment definitions.
The catalog discovery job loads these and runs the full discovery pipeline
(IGDB keyword queries → Twitch bridge → streams + clips → enrichment).

Add new definitions to cover genre gaps. Remove definitions for spaces
that have enough customer games to self-sustain.
