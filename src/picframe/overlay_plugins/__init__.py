"""Built-in overlay plugins shipped with picframe (#739, Phase 3).

This package exists so setuptools includes the built-in plugin directories
(``clock``, ``weather``, ``meta``) as package data. The
:class:`~picframe.core.services.bootstrapper.EnvironmentBootstrapper` copies
them into the user's ``~/.picframe/overlay-plugins/`` directory during
``picframe init`` so the :class:`~picframe.infrastructure.overlay.plugin_loader.PluginLoader`
discovers them alongside any user-created plugins.
"""
