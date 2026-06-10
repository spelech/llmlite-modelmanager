## Branching and Versioning Workflow
- All new features and bug fixes MUST be developed on dedicated feature branches.
- Direct commits to `main` are prohibited.
- Before merging any branch into `main`, I must present a summary of changes and wait for explicit user approval.
- Deployment images should be versioned or tagged appropriately to match the branch/release. Feature branch images are automatically tagged with the branch name (e.g. `:feat-vertex-canonical-discovery`).
- **NEVER** pull or restart containers immediately after pushing a commit. I MUST verify the successful completion of the CI/CD pipeline (e.g., via `gh run list`) and confirm the container revision matches the latest commit before proceeding with any updates.
