# Security policy

## Supported versions

RippleRack is in alpha. Only the latest release and the `main` branch receive security
fixes.

## Reporting a vulnerability

Please do not open a public issue for a security problem.

* **Preferred:** use GitHub's private vulnerability reporting. Open the repository's
  **Security** tab and choose **Report a vulnerability**
  ([direct link](https://github.com/IzanVil/RippleRack/security/advisories/new)).
* **Otherwise:** email [CONTACT_EMAIL] with "RippleRack security" in the subject.

Please include the RippleRack version (`ripplerack --version`), the smallest input file
that reproduces the problem, what you observed and the impact you see.

## What to expect

* An acknowledgement within **7 days**.
* An assessment and, if the report is valid, a plan for the fix. You will be kept
  informed of the progress.
* Coordinated disclosure: we ask you to keep the report private for up to **90 days**
  from the day you sent it, or until a fix is released, whichever comes first.
* Credit in the changelog, if you want it.

## Scope

RippleRack is a command line tool that reads the YAML files you give it, prints reports
and, only when asked with `-o`, writes one file. It makes no network requests and does not
run code from the files it reads.

In scope: code execution, unexpected file access or writes, or a denial of service
triggered by a crafted input file.

Out of scope: problems that require control of the machine or of the command line, and
vulnerabilities in dependencies that RippleRack does not expose. Report those to the
dependency, and tell us if RippleRack is affected.
