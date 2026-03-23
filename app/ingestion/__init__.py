# Ingestion module: discovers prospects from multiple platforms.
# Sources live in app.ingestion.sources/ and self-register via @register().
# New sources are added by dropping a new file in sources/ and importing it
# from sources/__init__.py. DiscoveryRunService in app.ingestion.service owns
# the end-to-end discovery workflow.
