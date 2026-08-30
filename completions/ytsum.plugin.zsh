# ytsum Oh My Zsh Plugin
# Adds tab completion for the ytsum CLI.
# This directory is automatically added to $fpath so zsh
# can find the _ytsum completion function.

fpath=("${0:h}" $fpath)
autoload -Uz _ytsum
