"""Meta Graph API simulator for tests: 10 fake accounts, each with a dozen or so campaigns and a year of posts.

Turn it on in config/settings.yaml: `graph_base_url: fake`. The program then talks to the simulator
exactly as to the real Meta (the same requests, pagination, errors), without internet.
All data is made up and repeatable.
"""
