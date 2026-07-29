# 用法（在仓库根目录）:
#   make -f scripts/Makefile help
#   make -f scripts/Makefile dist-zip
#   make -f scripts/Makefile clean-package-artifacts

ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
PROJECT_NAME := $(notdir $(ROOT))
DATE := $(shell date +%Y%m%d)
DIST_DIR := $(ROOT)/dist
STAGE_DIR := $(DIST_DIR)/$(PROJECT_NAME)
ZIP_PATH := $(DIST_DIR)/$(PROJECT_NAME)-$(DATE).zip

CLEAN_PATHS := \
	$(ROOT)/.venv \
	$(ROOT)/.pytest_cache \
	$(ROOT)/.mypy_cache \
	$(ROOT)/.ruff_cache \
	$(ROOT)/.tox \
	$(ROOT)/.nox \
	$(ROOT)/htmlcov \
	$(ROOT)/build \
	$(ROOT)/dist

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
	--exclude docs/node_modules \
	--exclude docs/.vitepress/cache \
	--exclude .electromind \
	--exclude artifacts \
	--exclude .DS_Store

.PHONY: help clean-package-artifacts dist-zip

help:
	@printf '%s\n' \
		'make -f scripts/Makefile clean-package-artifacts  # 清理 .venv 和测试/构建产物' \
		'make -f scripts/Makefile dist-zip                 # 清理后打包为 dist/$(PROJECT_NAME)-$(DATE).zip'

clean-package-artifacts:
	rm -rf $(CLEAN_PATHS)

dist-zip: clean-package-artifacts
	mkdir -p $(DIST_DIR)
	rsync -a $(RSYNC_EXCLUDES) $(ROOT)/ $(STAGE_DIR)/
	cd $(DIST_DIR) && zip -rq $(PROJECT_NAME)-$(DATE).zip $(PROJECT_NAME)
	rm -rf $(STAGE_DIR)
	@printf 'created %s\n' "$(ZIP_PATH)"
