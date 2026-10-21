# fossdoc_shop

Frappe app of the FossDoc shop (fossdoc.com): the calculation e-mail, the commercial offer PDF and orders.

Developed in the Docker dev bench of `tasmail/erpnext-infra` (`dev-bench/run.sh`), which mounts this directory.
Changes only by pull requests with tests (`dev-bench/run.sh test fossdoc_shop`).

The unit tests need a Frappe site, so they run in the dev bench; CI checks the style (`ruff`).
