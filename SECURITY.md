# Security

## Reporting a problem

- **Anything sensitive** (a way to read someone else's workspace, to get past sign-in, to run up someone's spend, to
  get a secret out): send Karim a message on [LinkedIn](https://linkedin.com/in/karimlameer). Not a public issue, and
  not email. Say what you found and how to see it; you will get a reply there.
- **Anything else** (a hardening idea, a dependency that needs updating, a limit that is not written down): open a
  [GitHub issue](https://github.com/klameer/anaplan-architect/issues).

## Run your own review

Please do. The code is MIT licensed and it is all here. Read it, run your scanner over it, point your own reviewer
at it. If you run it for other people, you should not take anyone's word for it, including ours.

Start with [what it protects and what it does not](docs/SECURITY.md): the design, the known limits, and the limits
that were accepted on purpose.

## Which version has been reviewed

A security review is run when the maintainer calls for one, not on every change, and each review is tied to a
commit. The [review log](docs/SECURITY-REVIEWS.md) lists each one: the commit by its full SHA, its tag, who reviewed it, what was
found, what was fixed and what was accepted. It also says how to check that the commit after a reviewed one changed
nothing but the log.

A review there is a separate AI reviewer that had no part in building the code. It is not a human audit and not a
penetration test of a live instance.

Commits after the latest reviewed one have not been reviewed. They are covered when a later entry in the log says
so, and not before.
