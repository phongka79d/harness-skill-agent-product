# Profiles

Project profiles define quality level, default threshold, project context,
verification policy, and immutable version/hash metadata. Profile IDs are
canonical and aliases resolve to the same canonical definition. Profile
changes require a new version; existing reviews retain the original resolved
profile hash. The verification policy declares TDD mode, broad-suite mode,
behavior-change kinds, and allowed machine-readable exception types.
