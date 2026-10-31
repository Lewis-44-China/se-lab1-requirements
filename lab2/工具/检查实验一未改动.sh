#!/usr/bin/env bash
# 检查实验一的交付文件与两个标签是否保持原样。
# 用法：bash lab2/工具/检查实验一未改动.sh
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

fail=0

check_diff() {
  local file="$1"
  if git diff --quiet lab1-final -- "$file"; then
    echo "✅ $file 与 lab1-final 一致"
  else
    echo "❌ $file 与 lab1-final 不一致"
    git diff --stat lab1-final -- "$file" || true
    fail=1
  fi
}

check_md5() {
  local file="$1" expected="$2"
  local actual
  actual=$(md5sum "$file" | awk '{print $1}')
  if [ "$actual" = "$expected" ]; then
    echo "✅ $file md5 = $actual"
  else
    echo "❌ $file md5 期望 $expected，实际 $actual"
    fail=1
  fi
}

check_ref() {
  local name="$1" expected="$2" actual
  actual=$(git rev-parse --verify "$name" 2>/dev/null || echo "missing")
  if [ "$actual" = "$expected" ]; then
    echo "✅ $name = $actual"
  else
    echo "❌ $name 期望 $expected，实际 $actual"
    fail=1
  fi
}

echo "=== 实验一文件内容 ==="
check_diff requirements.md
check_diff chat.txt
check_md5 requirements.md 3928c5d0e892ee177726e7db47fffe2e
check_md5 chat.txt 4275857443b38ff3f9b187c67d0aec31

echo "=== 实验一标签 ==="
check_ref "lab1-ai-draft^{commit}" 81c1055dab46c18cd7408451cb12baaced22f727
check_ref "lab1-final^{commit}" 7a1472f56b359e334448907bff4ba5bceff12a8d
check_ref "lab1-ai-draft" cc314353ea09c6b497b3ba7adc4de475fb0b0a3c
check_ref "lab1-final" 06c6684c8a6877c8a1a6403a37c7c5a316ca81bd

if [ "$fail" -ne 0 ]; then
  echo "=== 检查未通过 ==="
  exit 1
fi
echo "=== 检查通过：实验一文件与标签均未改动 ==="
