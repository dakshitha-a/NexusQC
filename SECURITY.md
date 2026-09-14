# Security

## Reporting a vulnerability

Do not open a public issue for a security problem. Email
[dma@temple.edu](mailto:dma@temple.edu) with what you found, how to reproduce
it, and what you think the impact is. You will get an acknowledgement within a
week and a fix or a reasoned answer within a month; if you hear nothing in a
week, send it again, because it did not arrive.

If the problem is in a deployment rather than in NexusQC itself (a
misconfigured server, an exposed port, an account issue), tell the
administrator of that deployment; they are named on its login page or by
whoever gave you the account.

## What is in scope

NexusQC runs quantum chemistry programs as subprocesses on the host it is
installed on, behind an approval gate, for authenticated users. Anything that
lets a user run something that was not approved, read another user's jobs or
files, escape the job directory, act as an administrator without being one, or
reach the host through the API is in scope. So is anything in the installer
or the update script that would expose the deployment beyond the addresses the
operator chose.

## Supported versions

The latest release. Fixes are not backported; a deployment is expected to
advance with `scripts/update.sh`, which reports what an update will do before
doing it.
