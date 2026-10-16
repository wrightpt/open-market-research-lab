# Public source release handoff

**Status: RELEASE CANDIDATE ONLY — NOT PUBLISHED.** This document does not authorize
production access, cloud deployment, financial transactions, or forum posting.

## Scope of this first release

Publish ONLY this separate, original, Apache-2.0 source tree: deterministic
synthetic market fixtures, declarative strategy schema, stdlib Python backtesting,
tests, agent onboarding, PR/issue templates, and a reproducibility challenge.
Do not include `trading-system`, GitOps, historical ClickHouse data, exchange
accounts, trading credentials, private machine information or the internal
`quant-market-api` service. This is an engineering reproducibility exercise,
**not a predictive trading strategy or performance claim**.

## Licensing decision and business trade-off

`LICENSE` is the standard Apache License 2.0. It permits outsiders to study,
modify, distribute and commercially reuse the code and the synthetic fixtures,
subject to its terms (including attribution and its patent provisions).
**Competitors can legally reuse this open-source code.** The intended future
business differentiator is separately licensed historical data, managed compute,
strategy evaluation, and support—not exclusivity over this benchmark code.

Third-party venue datasets and other repositories are not licensed by this file.
Contributors must have rights to license the content they submit; no secret
strategies or private datasets belong in PRs.

## Verified locally

- Original isolated development branch: `prototype/local-initial`.
- Baseline: 43 stdlib tests passed in a clean clone, fixture SHA-256 and JSON
  contract verified; checked-in synthetic holdout remains unevaluated.
- Security/CI contracts cover fork PRs using ephemeral GitHub-hosted runners,
  read-only token permissions, no private runners, no PR secrets, and full-SHA
  action pinning. These are tests and source review, NOT hosted execution proof.
- The publication candidate must be reverified after changes and have a fresh
  final commit and a no-personal-email Git history before upload.

## GitHub go/no-go

1. Create an EMPTY **private** GitHub repository under the verified owner,
   proposed name `open-market-research-lab`. Do not initialize a competing README,
   license, or Git ignore file. At the time of preparation it did not exist.
   Only switch its visibility to public after upload, security settings,
   hosted CI, and source/history review are all verified.
2. The current Workstation Commander Chrome session is signed out of GitHub,
   and the workstation's `gh` CLI has no authenticated account. The connected
   GitHub app can inspect existing repos but does not expose repository creation.
   **Do not enter or print GitHub passwords, PATs, or tokens through a tool.**
3. Before making the repository public, enable and verify GitHub private
   vulnerability reporting (Security > Advisories), review repository Actions
   policy, default token permissions, allowed runners, and public fork PR settings.
   Do not install self-hosted Actions runners or expose network paths to the cluster.
4. Confirm repository visibility and license reflect the explicit owner release
   decision, not an inferred GitHub default.
5. Inspect all files AND Git author/committer metadata, the single public history,
   workflow action pins, clean-clone Python 3.11/3.14 tests, and the security
   policy. If any check fails, keep the repo private/unpublished.
6. Upload/push only the sanitized release-candidate branch; verify the resulting
   public default branch, exact Git commit and clone URL from GitHub. Observe
   hosted CI on a real workflow run before calling hosted validation complete.
7. Public repo release is separate from forum posting. Verify the rules and
   approve the exact target and text first. Do not post private cluster endpoints,
   query credentials, real trade histories, or a fictitious GitHub URL.

## Separate future real-data milestone

Real market data must remain inaccessible until each venue's redistribution
terms are approved, dataset provenance/coverage is qualified, a dedicated
read-only product view and identity are provisioned, network/query quotas and
public authentication are independently tested, and isolation is verified.
Submitted code from anonymous users must never execute in the production
Kubernetes trading cluster. No step here opens a public database or runs
untrusted PRs on local workstation runners.

The candidate may be tested and committed locally without any external account
changes; **publication and Reddit posting are separate, verifiable events**.
