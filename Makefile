PROJECT_NAME := $(notdir $(CURDIR))
DATE := $(shell date +%Y%m%d)
DIST_DIR := dist
STAGE_DIR := $(DIST_DIR)/$(PROJECT_NAME)
ZIP_PATH := $(DIST_DIR)/$(PROJECT_NAME)-$(DATE).zip

CLEAN_PATHS := \
	.venv \
	.pytest_cache \
	.mypy_cache \
	.ruff_cache \
	.tox \
	.nox \
	htmlcov \
	build \
	dist \
	data/pagentv3_demo \
	data/pagentv3_cli

RSYNC_EXCLUDES := \
	--exclude .venv \
	--exclude __pycache__ \
	--exclude '*.pyc' \
	--exclude .pytest_cache \
	--exclude .mypy_cache \
	--exclude .ruff_cache \
	--exclude .tox \
	--exclude .nox \
	--exclude .coverage \
	--exclude htmlcov \
	--exclude build \
	--exclude dist \
	--exclude data/pagentv3_demo \
	--exclude data/pagentv3_cli \
	--exclude .DS_Store

.PHONY: help clean-package-artifacts dist-zip

help:
	@printf '%s\n' \
		'make clean-package-artifacts  # 清理 .venv 和测试/构建产物' \
		'make dist-zip                 # 清理后打包当前目录为 dist/$(PROJECT_NAME)-$(DATE).zip'

clean-package-artifacts:
	rm -rf $(CLEAN_PATHS)

dist-zip: clean-package-artifacts
	mkdir -p $(DIST_DIR)
	rsync -a $(RSYNC_EXCLUDES) ./ $(STAGE_DIR)/
	cd $(DIST_DIR) && zip -rq $(PROJECT_NAME)-$(DATE).zip $(PROJECT_NAME)
	rm -rf $(STAGE_DIR)
	@printf 'created %s\n' "$(ZIP_PATH)"
