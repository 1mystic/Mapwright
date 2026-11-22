---
name: mapwright
description: Keep a live map of the project while coding, and read it instead of exploring files. Use at the start of any coding task in a repository tracked by Mapwright, after each meaningful change (record a step), and when planning (todos). Saves tokens: the map replaces directory listings and file reads for structure questions.
---

# Mapwright

Mapwright builds the project's structure, architecture, data model, infrastructure, call graph and
flowcharts from the code itself. You never draw diagrams or describe files: you read the map, you
mark steps, and Mapwright computes what changed.

## Use the MCP tools when they are available

| When | Tool |
|---|---|
| Start of a task, or "where is X / how is this organised?" | `map` (optionally `focus: "path/"`) |
| Find code by name | `find` |
| Before editing a function: who calls it, what it calls, which tables it touches | `symbol` |
| After each meaningful change | `step` with a short title (what you did, not what you plan) |
| Plan items | `todo` add · done (with the symbol or file you changed as `evidence`) · list |
| You implemented a mechanism (caching, retries, queue, auth …) | `claim` with an id from `catalog` and the symbol |
| A relation the code cannot show (an event, a queue, an HTTP call between services) | `link` |
| One-line purpose of a module or function | `note` |

## Without MCP: the same through the shell

```bash
mapwright brief                       # the map, about 600 tokens
mapwright find NAME                   # locations
mapwright symbol NAME                 # callers, callees, tables, history
mapwright step "Add refunds"          # record a step
mapwright todo add "write tests for refunds"
mapwright todo done T3 --evidence RefundService.issue
mapwright claim retry-backoff PaymentClient.charge
mapwright catalog                     # concept ids
```

## Rules

- Read the map before opening files to learn structure. Open a file only to read or change its code.
- Record a step after each meaningful change. Do not list files in the title; they are computed.
- Mark a todo done only with evidence you actually changed. Unchanged evidence is reported as unverified.
- Claim a mechanism only where the code implements it. Claims are checked against the code and shown
  to the user as verified, weak or unverified.
- If the map and the code disagree, trust the code and say so.
