# Refine Hashrate Window Selection and Testing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand test coverage for Ocean hashrate window selection in the daemon and ensure robust fallback behavior.

**Architecture:** Update `tests/unit/test_daemon.py` with comprehensive test cases. Clean up redundant connectivity flag assignments in `hashbidder/daemon.py`.

**Tech Stack:** Python, Pytest, Decimal.

---

### Task 1: Expand tests in `tests/unit/test_daemon.py`

**Files:**
- Modify: `tests/unit/test_daemon.py`

- [ ] **Step 1: Replace the content of `tests/unit/test_daemon.py` with expanded tests.**

- [ ] **Step 2: Run tests to verify they pass.**

Run: `pytest tests/unit/test_daemon.py -v`

### Task 2: Clean up redundant code in `hashbidder/daemon.py`

**Files:**
- Modify: `hashbidder/daemon.py`

- [ ] **Step 1: Remove redundant connectivity flag assignments.**

### Task 3: Final verification and commit

- [ ] **Step 1: Run all tests.**

Run: `pytest tests/unit/test_daemon.py`

- [ ] **Step 2: Commit the changes.**
