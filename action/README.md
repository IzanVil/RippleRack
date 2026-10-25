# The RippleRack GitHub Action

This folder is a [composite action](https://docs.github.com/en/actions/sharing-automations/creating-actions/creating-a-composite-action).
It compares two versions of a datacenter file with RippleRack and tells a pull request what the
change breaks: a comment that every push updates, the outputs `severity`, `broken-count` and
`at-risk-count`, and, if you ask for it, a failed step.

```yaml
permissions:
  contents: read
  pull-requests: write

steps:
  - uses: actions/checkout@v7
  - uses: IzanVil/RippleRack/action@v0.2.4
    with:
      head: datacenter.yaml
      fail-on-breaking: "true"
```

The inputs, the outputs, what the comment looks like, forks, gating a merge and how to try the
action are in [docs/ci.md](../docs/ci.md#the-github-action).

| file | what it is |
|------|------------|
| `action.yml` | The inputs, the outputs and the two steps. Nothing is computed here. |
| `rr_action.py` | The glue, with only the standard library: install RippleRack from this checkout, find the base file, run `ripplerack diff` in JSON and Markdown, and carry the result to GitHub. |

The action installs the RippleRack that it comes with (`pip install` of the checkout that holds
this folder), so a tag of the repository is the action and RippleRack at once. Everything about
the datacenters stays in the `ripplerack` command; this folder only moves its results around.
