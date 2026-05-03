# Claude Marketplace

A [Claude Code](https://code.claude.com) plugin marketplace by [@rezrov](https://github.com/rezrov), hosting skills and plugins built for the Claude Code CLI.

## Requirements

- [Claude Code CLI](https://code.claude.com/docs/en/setup) installed and authenticated.

## Add this marketplace

From inside a Claude Code session:

```
/plugin marketplace add rezrov/claude-marketplace
```

Or from the shell:

```
claude plugin marketplace add rezrov/claude-marketplace
```

## Plugins

| Plugin | Description |
| --- | --- |
| [`kitty-cli-display-image`](./plugins/kitty-cli-display-image) | Display images in the terminal via the Kitty graphics protocol. |
| [`paperboy`](./plugins/paperboy) | Fetch, filter, and summarize RSS/news sources into a daily Obsidian-vault digest. |

Install any plugin with:

```
/plugin install <plugin-name>@rezrov-marketplace
```

For example:

```
/plugin install paperboy@rezrov-marketplace
```

## Updating

To pull the latest catalog and plugin versions:

```
/plugin marketplace update rezrov-marketplace
```

## Removing

```
/plugin marketplace remove rezrov-marketplace
```

Note: removing the marketplace also uninstalls any plugins you installed from it. To refresh without losing installs, use `update` instead.

## Contributing

Issues and pull requests are welcome. Each plugin lives under [`plugins/`](./plugins) and is registered in [`.claude-plugin/marketplace.json`](./.claude-plugin/marketplace.json).

To validate the marketplace locally after edits:

```
claude plugin validate .
```

## License

[MIT](./LICENSE)

## See also

- [Claude Code plugin marketplaces](https://code.claude.com/docs/en/plugin-marketplaces) — official documentation
- [Discover plugins](https://code.claude.com/docs/en/discover-plugins) — installing from any marketplace
