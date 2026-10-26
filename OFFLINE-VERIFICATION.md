# Offline verification boundary

Enable manual exact-head CI dispatch and explicit read-only repository permissions.

## Reproduce

`python3 -m unittest discover -s tests -v`

CI evidence must match the PR head SHA, not a previous green run. These fixtures do not execute a real paid Codex task.

## Rollback

Review the commit diff and use a new checkout of the pre-change commit for source rollback. Keep user data and live installations untouched. A source rollback is not permission to restore unsafe network exposure or bypass approval.
