# Documentation File Creation Policy

## Rule: Do Not Create Markdown Files Without Permission

**Applies to:** All `.md` files except specific architecture documentation

### Policy

1. **DO NOT** create new `.md` files unless explicitly requested by the user
2. **DO NOT** create documentation files proactively (summaries, guides, references, etc.)
3. **DO** update existing `.md` files when changes are made to the project
4. **DO** ask for permission before creating any new documentation

### Exceptions

The only `.md` files that may be created or updated without explicit permission are:

1. **Architecture diagrams** - Files containing mermaid diagrams showing:
   - System architecture
   - Data flows
   - Component relationships
   - Network topology
   
2. **Updates to existing documentation** - When code changes occur, update:
   - `README.md` - Keep architecture overview and setup instructions current
   - `DEPLOYMENT.md` - Add new deployment steps or troubleshooting
   - `IMPLEMENTATION_SUMMARY.md` - Update with completed features (if it exists)

### Rationale

- Reduces noise and clutter in the repository
- Keeps documentation focused and maintainable
- User maintains control over what documentation exists
- Architecture files are valuable for understanding system design
- Existing docs should stay current with code changes

### Examples

❌ **DO NOT CREATE:**
- `TESTING_GUIDE.md`
- `API_REFERENCE.md`
- `TROUBLESHOOTING.md`
- `QUICK_START.md`
- `SUMMARY.md`
- Any other new `.md` files

✅ **OK TO CREATE/UPDATE:**
- `ARCHITECTURE.md` (if showing mermaid diagrams)
- Updates to `README.md` (keeping it current)
- Updates to `DEPLOYMENT.md` (adding new steps)
- Mermaid diagrams in existing files

### When in Doubt

If you think a new markdown file would be helpful:
1. **ASK** the user first
2. Explain what you want to document
3. Wait for explicit approval
4. Consider if the content can go in an existing file instead
