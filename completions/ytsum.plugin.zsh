# ytsum Oh My Zsh Plugin
# Adds tab completion for the ytsum CLI.
# This directory is automatically added to $fpath so zsh
# can find the _ytsum completion function.

fpath=("${0:h}" $fpath)
autoload -Uz _ytsum

# Show flags at positional positions (after a URL) without requiring a '--' prefix.
# Without this, _arguments only offers options when the current word starts with '-'.
zstyle ':completion:*:*:ytsum:*' prefix-needed false
