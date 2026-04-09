# Contributing to speedster-harness

Thank you for your interest in contributing to speedster-harness! This guide outlines the contribution process.

## How to Submit Bug Reports

### Bug Report Template

When reporting a bug, please include:

1. **Expected behavior**: What should have happened
2. **Actual behavior**: What actually happened
3. **Steps to reproduce**: Clear steps to reproduce the issue
4. **Environment**:
   - Operating system
   - vLLM version
   - OpenCode version
   - Shell (bash/zsh/fish)
   - Relevant environment variables
5. **Logs/Output**: Relevant error messages or command output

### GitHub Issue Requirements

- Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md)
- Search existing issues before opening a new one
- Include all relevant details

## Feature Requests

### Feature Request Template

For feature requests:

1. **Use case**: Describe the problem or workflow you're trying to solve
2. **Proposed solution**: How should this feature work?
3. **Alternatives considered**: What other solutions have you tried?
4. **Additional context**: Any other relevant information

See [feature request template](.github/ISSUE_TEMPLATE/feature_request.md)

## Code Contributions

### Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork**:
   ```bash
   git clone https://github.com/YOUR_USERNAME/speedster-harness.git
   cd speedster-harness
   ```
3. **Create a feature branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```

### Development Guidelines

#### Code Quality

- **ShellCheck**: All shell scripts must pass `shellcheck -S` (strict mode)
  ```bash
  shellcheck -S opencode-setup.sh
  ```
- Use the pre-commit hooks:
  ```bash
  pip install pre-commit
  pre-commit install
  ```
- Maintain consistent indentation (4 spaces for YAML, 2 spaces for JSON)
- No trailing whitespace

#### Commit Messages

Use conventional commit format:
```
<type>(<scope>): <subject>

[optional body]
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `refactor`: Code refactoring
- `chore`: Maintenance tasks
- `perf`: Performance improvements
- `security`: Security fixes

Examples:
```
feat: add support for custom model names
fix: handle empty vLLM model responses
docs: expand troubleshooting section
```

### Submitting Pull Requests

1. Ensure all tests pass and code passes shellcheck
2. Squash commits if needed (keep commit history clean)
3. Update documentation as needed (README, CHANGELOG)
4. Fill out the [pull request template](.github/PULL_REQUEST_TEMPLATE.md)

### Testing

Before submitting:
- Run `bash -n opencode-setup.sh` for syntax validation
- Test with your vLLM setup if possible
- Verify backup functionality works correctly
- Check file permissions are set correctly

## Contact & Support

- **Support inquiries**: Use GitHub Issues only
- **Bug reports**: Use GitHub Issues with bug report template
- **Feature requests**: Use GitHub Issues with feature request template
- **Code contributions**: Submit Pull Requests

We respond to all issues within reasonable timeframes.

## Code of Conduct

- Be respectful and inclusive
- Focus on constructive feedback
- Accept constructive criticism gracefully
- Prioritize the community's interests

## Review Process

1. Maintainer reviews the PR
2. May request changes or clarifications
3. Once approved, changes are merged
4. Maintainer handles merging to main branch

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
