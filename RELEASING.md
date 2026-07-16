# Releasing fencekit

## First PyPI release

1. Create a PyPI account, verify the email address, and enable two-factor
   authentication.
2. Open the PyPI account publishing page:
   `https://pypi.org/manage/account/publishing/`.
3. Add a pending GitHub publisher with these values:

   - PyPI project name: `fencekit`
   - Owner: `ahmed5145`
   - Repository: `fencekit`
   - Workflow: `release.yml`
   - Environment: `pypi`

4. In the GitHub repository, open Settings, Environments, then create an
   environment named `pypi`.
5. Add yourself as a required reviewer for that environment. Leave
   self-approval enabled because this repository has one maintainer.

The pending publisher does not reserve the package name. Publish the first release
soon after creating it.

## Release process

1. Set the version in `pyproject.toml` and `src/fencekit/_version.py`.
2. Add the release date and changes to `CHANGELOG.md`.
3. Run the test suite and build the distributions.
4. Commit the release changes and wait for CI to pass on `main`.
5. Create a GitHub Release whose tag is `v<version>`, such as `v0.1.0`.
6. Approve the `pypi` deployment when GitHub prompts for review.

Publishing the GitHub Release starts `.github/workflows/release.yml`. The workflow
checks that the tag matches the package version, builds the wheel and source
archive, checks their metadata, then publishes them through PyPI Trusted
Publishing.

PyPI release files cannot be replaced. Fix a bad release with a new version.
