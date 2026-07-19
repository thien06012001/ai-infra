---
name: grilling
description: Relentlessly interview the user about a plan, decision, or idea — one question at a time — until you reach shared understanding. Use when the user wants to stress-test their thinking, asks to be "grilled", or is about to commit to a design whose assumptions have not been examined.
---

# Grilling

Interview the user relentlessly about every aspect of the thing under discussion until you reach a shared understanding. Walk down each branch of the decision tree, resolving dependencies between decisions one at a time.

## The rules

**Ask one question at a time.** Wait for the answer before asking the next. Asking several questions at once is bewildering and produces shallow answers to all of them.

**Give your recommended answer with every question.** A bare question offloads the thinking; a question plus a recommendation gives the user something to push against. Say which way you lean and why.

**Look up facts; ask only about decisions.** If something can be settled by reading the filesystem, running a command, or checking a tool, go and settle it. Never spend a question on something you could have found out yourself. The *decisions*, though, belong to the user — put each one to them and wait.

**Do not act until the user confirms.** Grilling produces shared understanding, not artifacts and not code. When you believe you have reached it, say so and stop. The user decides what happens next.

## When this applies

Reach for grilling when the cost of a wrong assumption is higher than the cost of the interview — a design about to be built, a migration about to run, a decision that will be expensive to reverse.

This is a *primitive*, not a process. It produces no document and opens no gate. When the situation calls for a full design flow that ends in a committed spec, `superpowers:brainstorming` is the heavier tool and the right one. Grilling is what you use when you only want the questions.

## Provenance

Extracted from [`mattpocock/skills`](https://github.com/mattpocock/skills) (MIT, Matt Pocock), evaluated 2026-07-19. The upstream plugin ships twenty-three skills and was not installed — most of them duplicate skills already present in a default setup, and a plugin manifest cannot be partially enabled. This one was taken by hand instead, which is what the licence is for.
