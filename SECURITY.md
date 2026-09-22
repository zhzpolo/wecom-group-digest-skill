# Security

This project is for a user's own locally synchronized WeCom account. Do not use it to access another person's account, bypass remote authentication, or collect login credentials.

Never include real exports, databases, WAL/SHM files, account IDs, group IDs, local machine paths, memory dumps, or raw keys in issues. Reproduce defects with fictional fixtures.

The command keeps a validated database key in one process only and overwrites its mutable buffer on exit. Python/runtime copies and OS swap cannot provide forensic-grade erasure. The tool does not create plaintext SQLite files, but `messages.json` and reports intentionally contain sensitive chat text and must remain private.

Report key persistence, plaintext database leakage, or unauthorized process access privately through GitHub Security Advisories.
