# Changelog

## [0.18.0](https://github.com/spelech/llmlite-modelmanager/compare/v0.17.2...v0.18.0) (2026-10-28)


### Features

* **sync:** auto-resolve LiteLLM model_group_alias for latest family models and sync only aliases to OpenCode (v0.18.0) ([#22](https://github.com/spelech/llmlite-modelmanager/issues/22)) ([0f1fb0f](https://github.com/spelech/llmlite-modelmanager/commit/0f1fb0f2979e38bec207cb9bcc042fceac6afa27))


### Bug Fixes

* **health:** use OpenRouter /models/{id}/endpoints for 0-token catalog health probe ([5cb0c39](https://github.com/spelech/llmlite-modelmanager/commit/5cb0c39c3ecbc4a47b816815bc21dd6338018420))
* **sync:** preserve custom agy models, prune removed models from opencode, disable default librechat sync (v0.17.3) ([84efe10](https://github.com/spelech/llmlite-modelmanager/commit/84efe10cd97e870d2afe648dc1aabf3901be2505))
* **sync:** preserve custom agy models, prune removed models from opencode, disable default librechat sync (v0.17.3) ([faa8dac](https://github.com/spelech/llmlite-modelmanager/commit/faa8dac08081c8f9c61ac2a7c5ee06727fbd2641))
* **vertex:** use per-token and cached-token pricing instead of per-character and filter batch SKUs ([#23](https://github.com/spelech/llmlite-modelmanager/issues/23)) ([ef9783e](https://github.com/spelech/llmlite-modelmanager/commit/ef9783ed525f49fc6d6515cf9e5755d3944a7843))


### Documentation

* add custom 1280x640 social preview card (.github/social-preview.svg) ([7aafcf6](https://github.com/spelech/llmlite-modelmanager/commit/7aafcf6483978b8c3c03469904329e73685fa86d))
