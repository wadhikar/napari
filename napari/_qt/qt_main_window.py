"""
Custom Qt widgets that serve as native objects that the public-facing elements
wrap.
"""
import inspect
import os
import sys
import time
from itertools import chain, repeat
from typing import Dict

from qtpy.QtCore import QPoint, QProcess, QSize, Qt
from qtpy.QtGui import QIcon, QKeySequence
from qtpy.QtWidgets import (
    QAction,
    QApplication,
    QDialog,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QShortcut,
    QWidget,
)

from .. import plugins
from ..utils import config, perf
from ..utils.io import imsave
from ..utils.misc import in_jupyter, running_as_bundled_app
from ..utils.settings import SETTINGS
from ..utils.translations import trans
from .dialogs.preferences_dialog import PreferencesDialog
from .dialogs.qt_about import QtAbout
from .dialogs.qt_plugin_dialog import QtPluginDialog
from .dialogs.qt_plugin_report import QtPluginErrReporter
from .dialogs.screenshot_dialog import ScreenshotDialog
from .perf.qt_debug_menu import DebugMenu
from .qt_event_loop import NAPARI_ICON_PATH, get_app, quit_app
from .qt_resources import get_stylesheet
from .qt_viewer import QtViewer
from .utils import QImg2array, qbytearray_to_str, str_to_qbytearray
from .widgets.qt_viewer_dock_widget import QtViewerDockWidget


class _QtMainWindow(QMainWindow):
    # This was added so that someone can patch
    # `napari._qt.qt_main_window._QtMainWindow._window_icon`
    # to their desired window icon
    _window_icon = NAPARI_ICON_PATH

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._quit_app = False
        self.setWindowIcon(QIcon(self._window_icon))
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setUnifiedTitleAndToolBarOnMac(True)
        center = QWidget(self)
        center.setLayout(QHBoxLayout())
        center.layout().setContentsMargins(4, 0, 4, 0)
        self.setCentralWidget(center)

        self._maximized_flag = False
        self._preferences_dialog = None
        self._preferences_dialog_size = QSize()
        self._status_bar = self.statusBar()

        # set SETTINGS plugin defaults.
        plugins.load_settings_plugin_defaults(SETTINGS)

        # set the values in plugins to match the ones saved in SETTINGS
        if SETTINGS.plugins.call_order is not None:
            plugins.plugin_manager.set_call_order(SETTINGS.plugins.call_order)

    def _load_window_settings(self):
        """
        Load window layout settings from configuration.
        """
        window_size = SETTINGS.application.window_size
        window_state = SETTINGS.application.window_state
        preferences_dialog_size = SETTINGS.application.preferences_size
        window_position = SETTINGS.application.window_position

        # It's necessary to verify if the window/position value is valid with the current screen.
        width, height = window_position
        screen_shape = QApplication.desktop().geometry()
        current_width = screen_shape.width()
        current_height = screen_shape.height()
        if current_width < width or current_height < height:
            window_position = (self.x(), self.y())

        window_maximized = SETTINGS.application.window_maximized
        window_fullscreen = SETTINGS.application.window_fullscreen
        return (
            window_state,
            window_size,
            window_position,
            window_maximized,
            window_fullscreen,
            preferences_dialog_size,
        )

    def _get_window_settings(self):
        """
        Return current window settings.

        Symmetric to the 'set_window_settings' setter.
        """
        window_size = (self.width(), self.height())
        window_fullscreen = self.isFullScreen()

        if window_fullscreen:
            window_maximized = self._maximized_flag
        else:
            window_maximized = self.isMaximized()

        window_position = (self.x(), self.y())
        preferences_dialog_size = (
            self._preferences_dialog_size.width(),
            self._preferences_dialog_size.height(),
        )
        window_state = qbytearray_to_str(self.saveState())
        return (
            window_state,
            window_size,
            window_position,
            window_maximized,
            window_fullscreen,
            preferences_dialog_size,
        )

    def _set_window_settings(
        self,
        window_state,
        window_size,
        window_position,
        window_maximized,
        window_fullscreen,
        preferences_dialog_size,
    ):
        """
        Set window settings.

        Symmetric to the 'get_window_settings' accessor.
        """
        self.setUpdatesEnabled(False)
        self.setWindowState(Qt.WindowNoState)

        if preferences_dialog_size:
            self._preferences_dialog_size = QSize(*preferences_dialog_size)

        if window_position:
            window_position = QPoint(*window_position)
            self.move(window_position)

        if window_size:
            window_size = QSize(*window_size)
            self.resize(window_size)

        if window_state:
            self.restoreState(str_to_qbytearray(window_state))

        if window_fullscreen:
            self.setWindowState(Qt.WindowFullScreen)
            self._maximized_flag = window_maximized
        elif window_maximized:
            self.setWindowState(Qt.WindowMaximized)

        self.setUpdatesEnabled(True)

    def _save_current_window_settings(self):
        """Save the current geometry of the main window."""
        (
            window_state,
            window_size,
            window_position,
            window_maximized,
            window_fullscreen,
            preferences_dialog_size,
        ) = self._get_window_settings()

        SETTINGS.application.window_size = window_size
        SETTINGS.application.window_maximized = window_maximized
        SETTINGS.application.window_fullscreen = window_fullscreen
        SETTINGS.application.window_position = window_position
        SETTINGS.application.window_state = window_state
        SETTINGS.application.preferences_size = preferences_dialog_size
        SETTINGS.application.window_statusbar = not self._status_bar.isHidden()

    def _update_preferences_dialog_size(self, size):
        """Save preferences dialog size."""
        self._preferences_dialog_size = size

    def close(self, quit_app=False):
        """Override to handle closing app or just the window."""
        self._quit_app = quit_app
        return super().close()

    def close_window(self):
        """Close active dialog or active window."""
        parent = QApplication.focusWidget()
        while parent is not None:
            if isinstance(parent, QMainWindow):
                self.close()
                break

            if isinstance(parent, QDialog):
                parent.close()
                break

            parent = parent.parent()

    def closeEvent(self, event):
        """This method will be called when the main window is closing.

        Regardless of whether cmd Q, cmd W, or the close button is used...
        """
        # Close any floating dockwidgets
        for dock in self.findChildren(QtViewerDockWidget):
            if dock.isFloating():
                dock.setFloating(False)

        if SETTINGS.application.save_window_geometry:
            self._save_current_window_settings()

        # On some versions of Darwin, exiting while fullscreen seems to tickle
        # some bug deep in NSWindow.  This forces the fullscreen keybinding
        # test to complete its draw cycle, then pop back out of fullscreen.
        if self.isFullScreen():
            self.showNormal()
            for _i in range(5):
                time.sleep(0.1)
                QApplication.processEvents()

        if self._quit_app:
            quit_app()

        event.accept()

    def restart(self):
        """Restart the napari application in a detached process."""
        process = QProcess()
        process.setProgram(sys.executable)

        if not running_as_bundled_app():
            process.setArguments(sys.argv)

        process.startDetached()
        self.close(quit_app=True)


class Window:
    """Application window that contains the menu bar and viewer.

    Parameters
    ----------
    viewer : napari.components.ViewerModel
        Contained viewer widget.

    Attributes
    ----------
    file_menu : qtpy.QtWidgets.QMenu
        File menu.
    help_menu : qtpy.QtWidgets.QMenu
        Help menu.
    main_menu : qtpy.QtWidgets.QMainWindow.menuBar
        Main menubar.
    qt_viewer : QtViewer
        Contained viewer widget.
    view_menu : qtpy.QtWidgets.QMenu
        View menu.
    window_menu : qtpy.QtWidgets.QMenu
        Window menu.
    """

    def __init__(self, viewer, *, show: bool = True):
        # create QApplication if it doesn't already exist
        get_app()

        # Connect the Viewer and create the Main Window
        self._qt_window = _QtMainWindow()
        self.qt_viewer = QtViewer(viewer)
        self._qt_window.centralWidget().layout().addWidget(self.qt_viewer)
        self._qt_window.setWindowTitle(viewer.title)
        self._status_bar = self._qt_window.statusBar()

        # Dictionary holding dock widgets
        self._dock_widgets: Dict[str, QtViewerDockWidget] = {}

        # since we initialize canvas before window, we need to manually connect them again.
        if self._qt_window.windowHandle() is not None:
            self._qt_window.windowHandle().screenChanged.connect(
                self.qt_viewer.canvas._backend.screen_changed
            )

        self._add_menubar()
        self._add_file_menu()
        self._add_view_menu()
        self._add_window_menu()
        self._add_plugins_menu()
        self._add_help_menu()

        self._status_bar.showMessage(trans._('Ready'))
        self._help = QLabel('')
        self._status_bar.addPermanentWidget(self._help)

        self.qt_viewer.viewer.theme = SETTINGS.appearance.theme
        self._update_theme()

        self._add_viewer_dock_widget(self.qt_viewer.dockConsole, tabify=False)
        self._add_viewer_dock_widget(
            self.qt_viewer.dockLayerControls, tabify=False
        )
        self._add_viewer_dock_widget(
            self.qt_viewer.dockLayerList, tabify=False
        )
        self.window_menu.addSeparator()

        SETTINGS.appearance.events.theme.connect(self._update_theme)

        viewer.events.status.connect(self._status_changed)
        viewer.events.help.connect(self._help_changed)
        viewer.events.title.connect(self._title_changed)
        viewer.events.theme.connect(self._update_theme)

        if perf.USE_PERFMON:
            # Add DebugMenu and dockPerformance if using perfmon.
            self._debug_menu = DebugMenu(self)
            self._add_viewer_dock_widget(self.qt_viewer.dockPerformance)
        else:
            self._debug_menu = None

        if show:
            self.show()

    def __getattr__(self, name):
        if name == 'raw_stylesheet':
            import warnings

            warnings.warn(
                (
                    trans._(
                        "The 'raw_stylesheet' attribute is deprecated and will be "
                        "removed in version 0.4.7.  Please use "
                        "`napari.qt.get_stylesheet` instead"
                    )
                ),
                category=DeprecationWarning,
                stacklevel=2,
            )
            return get_stylesheet()

        return object.__getattribute__(self, name)

    def _add_menubar(self):
        """Add menubar to napari app."""
        self.main_menu = self._qt_window.menuBar()
        # Menubar shortcuts are only active when the menubar is visible.
        # Therefore, we set a global shortcut not associated with the menubar
        # to toggle visibility, *but*, in order to not shadow the menubar
        # shortcut, we disable it, and only enable it when the menubar is
        # hidden. See this stackoverflow link for details:
        # https://stackoverflow.com/questions/50537642/how-to-keep-the-shortcuts-of-a-hidden-widget-in-pyqt5
        self._main_menu_shortcut = QShortcut(
            QKeySequence('Ctrl+M'), self._qt_window
        )
        self._main_menu_shortcut.activated.connect(
            self._toggle_menubar_visible
        )
        self._main_menu_shortcut.setEnabled(False)

    def _toggle_menubar_visible(self):
        """Toggle visibility of app menubar.

        This function also disables or enables a global keyboard shortcut to
        show the menubar, since menubar shortcuts are only available while the
        menubar is visible.
        """
        if self.main_menu.isVisible():
            self.main_menu.setVisible(False)
            self._main_menu_shortcut.setEnabled(True)
        else:
            self.main_menu.setVisible(True)
            self._main_menu_shortcut.setEnabled(False)

    def _add_file_menu(self):
        """Add 'File' menu to app menubar."""
        open_images = QAction(trans._('Open File(s)...'), self._qt_window)
        open_images.setShortcut('Ctrl+O')
        open_images.setStatusTip(trans._('Open file(s)'))
        open_images.triggered.connect(self.qt_viewer._open_files_dialog)

        open_stack = QAction(
            trans._('Open Files as Stack...'), self._qt_window
        )
        open_stack.setShortcut('Ctrl+Alt+O')
        open_stack.setStatusTip(trans._('Open files'))
        open_stack.triggered.connect(
            self.qt_viewer._open_files_dialog_as_stack_dialog
        )

        open_folder = QAction(trans._('Open Folder...'), self._qt_window)
        open_folder.setShortcut('Ctrl+Shift+O')
        open_folder.setStatusTip(trans._('Open a folder'))
        open_folder.triggered.connect(self.qt_viewer._open_folder_dialog)

        # OS X will rename this to Quit and put it in the app menu.
        preferences = QAction(trans._('Preferences'), self._qt_window)
        preferences.setShortcut('Ctrl+Shift+P')
        preferences.setStatusTip(trans._('Open preferences dialog'))
        preferences.setMenuRole(QAction.PreferencesRole)
        preferences.triggered.connect(self._open_preferences)

        save_selected_layers = QAction(
            trans._('Save Selected Layer(s)...'), self._qt_window
        )
        save_selected_layers.setShortcut('Ctrl+S')
        save_selected_layers.setStatusTip(trans._('Save selected layers'))
        save_selected_layers.triggered.connect(
            lambda: self.qt_viewer._save_layers_dialog(selected=True)
        )

        save_all_layers = QAction(
            trans._('Save All Layers...'), self._qt_window
        )
        save_all_layers.setShortcut('Ctrl+Shift+S')
        save_all_layers.setStatusTip(trans._('Save all layers'))
        save_all_layers.triggered.connect(
            lambda: self.qt_viewer._save_layers_dialog(selected=False)
        )

        screenshot = QAction(trans._('Save Screenshot...'), self._qt_window)
        screenshot.setShortcut('Alt+S')
        screenshot.setStatusTip(
            trans._('Save screenshot of current display, default .png')
        )
        screenshot.triggered.connect(self.qt_viewer._screenshot_dialog)

        screenshot_wv = QAction(
            trans._('Save Screenshot with Viewer...'), self._qt_window
        )
        screenshot_wv.setShortcut('Alt+Shift+S')
        screenshot_wv.setStatusTip(
            trans._(
                'Save screenshot of current display with the viewer, default .png'
            )
        )
        screenshot_wv.triggered.connect(self._screenshot_dialog)

        # OS X will rename this to Quit and put it in the app menu.
        # This quits the entire QApplication and all windows that may be open.
        quitAction = QAction(trans._('Exit'), self._qt_window)
        quitAction.setShortcut('Ctrl+Q')
        quitAction.setMenuRole(QAction.QuitRole)
        quitAction.triggered.connect(
            lambda: self._qt_window.close(quit_app=True)
        )

        if running_as_bundled_app():
            restartAction = QAction(trans._('Restart'), self._qt_window)
            restartAction.triggered.connect(self._qt_window.restart)

        closeAction = QAction(trans._('Close Window'), self._qt_window)
        closeAction.setShortcut('Ctrl+W')
        closeAction.triggered.connect(self._qt_window.close_window)

        from ..plugins import _sample_data

        open_sample_menu = QMenu(trans._('Open Sample'), self._qt_window)
        for plugin_name, samples in _sample_data.items():
            multiprovider = len(samples) > 1
            if multiprovider:
                menu = QMenu(plugin_name, self._qt_window)
                open_sample_menu.addMenu(menu)
            else:
                menu = open_sample_menu

            for samp_name, samp_dict in samples.items():
                display_name = samp_dict['display_name']
                if multiprovider:
                    action = QAction(display_name, parent=self._qt_window)
                else:
                    full_name = plugins.menu_item_template.format(
                        plugin_name, display_name
                    )
                    action = QAction(full_name, parent=self._qt_window)

                def _add_sample(*args, plg=plugin_name, smp=samp_name):
                    self.qt_viewer.viewer.open_sample(plg, smp)

                menu.addAction(action)
                action.triggered.connect(_add_sample)

        self.file_menu = self.main_menu.addMenu(trans._('&File'))
        self.file_menu.addAction(open_images)
        self.file_menu.addAction(open_stack)
        self.file_menu.addAction(open_folder)
        self.file_menu.addMenu(open_sample_menu)
        self.file_menu.addSeparator()
        self.file_menu.addAction(preferences)
        self.file_menu.addSeparator()
        self.file_menu.addAction(save_selected_layers)
        self.file_menu.addAction(save_all_layers)
        self.file_menu.addAction(screenshot)
        self.file_menu.addAction(screenshot_wv)
        self.file_menu.addSeparator()
        self.file_menu.addAction(closeAction)

        if running_as_bundled_app():
            self.file_menu.addAction(restartAction)

        self.file_menu.addAction(quitAction)

    def _open_preferences(self):
        """Edit preferences from the menubar."""
        if self._qt_window._preferences_dialog is None:
            win = PreferencesDialog(parent=self._qt_window)
            win.resized.connect(
                self._qt_window._update_preferences_dialog_size
            )

            if self._qt_window._preferences_dialog_size:
                win.resize(self._qt_window._preferences_dialog_size)

            self._qt_window._preferences_dialog = win
            win.closed.connect(self._on_preferences_closed)
            win.show()
        else:
            self._qt_window._preferences_dialog.raise_()

    def _on_preferences_closed(self):
        """Reset preferences dialog variable."""
        self._qt_window._preferences_dialog = None

    def _add_view_menu(self):
        """Add 'View' menu to app menubar."""
        toggle_visible = QAction(
            trans._('Toggle Menubar Visibility'), self._qt_window
        )
        toggle_visible.setShortcut('Ctrl+M')
        toggle_visible.setStatusTip(trans._('Hide Menubar'))
        toggle_visible.triggered.connect(self._toggle_menubar_visible)
        toggle_fullscreen = QAction(
            trans._('Toggle Full Screen'), self._qt_window
        )
        toggle_fullscreen.setShortcut('Ctrl+F')
        toggle_fullscreen.setStatusTip(trans._('Toggle full screen'))
        toggle_fullscreen.triggered.connect(self._toggle_fullscreen)
        toggle_play = QAction(trans._('Toggle Play'), self._qt_window)
        toggle_play.triggered.connect(self._toggle_play)
        toggle_play.setShortcut('Ctrl+Alt+P')
        toggle_play.setStatusTip(trans._('Toggle Play'))

        self.view_menu = self.main_menu.addMenu(trans._('&View'))
        self.view_menu.addAction(toggle_fullscreen)
        self.view_menu.addAction(toggle_visible)
        self.view_menu.addAction(toggle_play)
        self.view_menu.addSeparator()

        # Add octree actions.
        if config.async_octree:
            toggle_outline = QAction(
                trans._('Toggle Chunk Outlines'), self._qt_window
            )
            toggle_outline.triggered.connect(
                self.qt_viewer._toggle_chunk_outlines
            )
            toggle_outline.setShortcut('Ctrl+Alt+O')
            toggle_outline.setStatusTip(trans._('Toggle Chunk Outlines'))
            self.view_menu.addAction(toggle_outline)

        # Add axes menu
        axes_menu = QMenu(trans._('Axes'), parent=self._qt_window)
        axes_visible_action = QAction(
            trans._('Visible'),
            parent=self._qt_window,
            checkable=True,
            checked=self.qt_viewer.viewer.axes.visible,
        )
        axes_visible_action.triggered.connect(self._toggle_axes_visible)
        axes_colored_action = QAction(
            trans._('Colored'),
            parent=self._qt_window,
            checkable=True,
            checked=self.qt_viewer.viewer.axes.colored,
        )
        axes_colored_action.triggered.connect(self._toggle_axes_colored)
        axes_labels_action = QAction(
            trans._('Labels'),
            parent=self._qt_window,
            checkable=True,
            checked=self.qt_viewer.viewer.axes.labels,
        )
        axes_labels_action.triggered.connect(self._toggle_axes_labels)
        axes_dashed_action = QAction(
            trans._('Dashed'),
            parent=self._qt_window,
            checkable=True,
            checked=self.qt_viewer.viewer.axes.dashed,
        )
        axes_dashed_action.triggered.connect(self._toggle_axes_dashed)
        axes_arrows_action = QAction(
            trans._('Arrows'),
            parent=self._qt_window,
            checkable=True,
            checked=self.qt_viewer.viewer.axes.arrows,
        )
        axes_arrows_action.triggered.connect(self._toggle_axes_arrows)
        axes_menu.addAction(axes_visible_action)
        axes_menu.addAction(axes_colored_action)
        axes_menu.addAction(axes_labels_action)
        axes_menu.addAction(axes_dashed_action)
        axes_menu.addAction(axes_arrows_action)
        self.view_menu.addMenu(axes_menu)

        # Add scale bar menu
        scale_bar_menu = QMenu(trans._('Scale Bar'), parent=self._qt_window)
        scale_bar_visible_action = QAction(
            trans._('Visible'),
            parent=self._qt_window,
            checkable=True,
            checked=self.qt_viewer.viewer.scale_bar.visible,
        )
        scale_bar_visible_action.triggered.connect(
            self._toggle_scale_bar_visible
        )
        scale_bar_colored_action = QAction(
            trans._('Colored'),
            parent=self._qt_window,
            checkable=True,
            checked=self.qt_viewer.viewer.scale_bar.colored,
        )
        scale_bar_colored_action.triggered.connect(
            self._toggle_scale_bar_colored
        )
        scale_bar_ticks_action = QAction(
            trans._('Ticks'),
            parent=self._qt_window,
            checkable=True,
            checked=self.qt_viewer.viewer.scale_bar.ticks,
        )
        scale_bar_ticks_action.triggered.connect(self._toggle_scale_bar_ticks)
        scale_bar_menu.addAction(scale_bar_visible_action)
        scale_bar_menu.addAction(scale_bar_colored_action)
        scale_bar_menu.addAction(scale_bar_ticks_action)
        self.view_menu.addMenu(scale_bar_menu)

        self.view_menu.addSeparator()

    def _add_window_menu(self):
        """Add 'Window' menu to app menubar."""
        clear_action = QAction(trans._("Remove Dock Widgets"), self._qt_window)
        clear_action.setStatusTip(trans._('Remove all dock widgets'))
        clear_action.triggered.connect(
            lambda e: self.remove_dock_widget('all')
        )

        self.window_menu = self.main_menu.addMenu(trans._('&Window'))
        self.window_menu.addAction(clear_action)
        self.window_menu.addSeparator()

    def _add_plugins_menu(self):
        """Add 'Plugins' menu to app menubar."""
        self.plugins_menu = self.main_menu.addMenu(trans._('&Plugins'))

        pip_install_action = QAction(
            trans._("Install/Uninstall Package(s)..."), self._qt_window
        )
        pip_install_action.triggered.connect(self._show_plugin_install_dialog)
        self.plugins_menu.addAction(pip_install_action)

        report_plugin_action = QAction(
            trans._("Plugin Errors..."), self._qt_window
        )
        report_plugin_action.setStatusTip(
            trans._(
                'Review stack traces for plugin exceptions and notify developers'
            )
        )
        report_plugin_action.triggered.connect(self._show_plugin_err_reporter)
        self.plugins_menu.addAction(report_plugin_action)

        self._plugin_dock_widget_menu = QMenu(
            trans._('Add Dock Widget'), self._qt_window
        )

        if not plugins.dock_widgets:
            plugins.discover_dock_widgets()

        # Add a menu item (QAction) for each available plugin widget
        docks = zip(repeat("dock"), plugins.dock_widgets.items())
        funcs = zip(repeat("func"), plugins.function_widgets.items())
        for hook_type, (plugin_name, widgets) in chain(docks, funcs):
            multiprovider = len(widgets) > 1
            if multiprovider:
                menu = QMenu(plugin_name, self._qt_window)
                self._plugin_dock_widget_menu.addMenu(menu)
            else:
                menu = self._plugin_dock_widget_menu

            for wdg_name in widgets:
                key = (plugin_name, wdg_name)
                if multiprovider:
                    action = QAction(wdg_name, parent=self._qt_window)
                else:
                    full_name = plugins.menu_item_template.format(*key)
                    action = QAction(full_name, parent=self._qt_window)

                def _add_widget(*args, key=key, hook_type=hook_type):
                    if hook_type == 'dock':
                        self.add_plugin_dock_widget(*key)
                    else:
                        self._add_plugin_function_widget(*key)

                menu.addAction(action)
                action.triggered.connect(_add_widget)

        self.plugins_menu.addMenu(self._plugin_dock_widget_menu)

    def _show_plugin_install_dialog(self):
        """Show dialog that allows users to sort the call order of plugins."""

        self.plugin_dialog = QtPluginDialog(self._qt_window)
        self.plugin_dialog.exec_()

    def _show_plugin_err_reporter(self):
        """Show dialog that allows users to review and report plugin errors."""
        QtPluginErrReporter(parent=self._qt_window).exec_()

    def _add_help_menu(self):
        """Add 'Help' menu to app menubar."""
        self.help_menu = self.main_menu.addMenu(trans._('&Help'))

        about_action = QAction(trans._("napari Info"), self._qt_window)
        about_action.setShortcut("Ctrl+/")
        about_action.setStatusTip(trans._('About napari'))
        about_action.triggered.connect(
            lambda e: QtAbout.showAbout(self.qt_viewer, self._qt_window)
        )
        self.help_menu.addAction(about_action)

        about_key_bindings = QAction(
            trans._("Show Key Bindings"), self._qt_window
        )
        about_key_bindings.setShortcut("Ctrl+Alt+/")
        about_key_bindings.setShortcutContext(Qt.ApplicationShortcut)
        about_key_bindings.setStatusTip(trans._('key_bindings'))
        about_key_bindings.triggered.connect(
            self.qt_viewer.show_key_bindings_dialog
        )
        self.help_menu.addAction(about_key_bindings)

    def _toggle_scale_bar_visible(self, state):
        self.qt_viewer.viewer.scale_bar.visible = state

    def _toggle_scale_bar_colored(self, state):
        self.qt_viewer.viewer.scale_bar.colored = state

    def _toggle_scale_bar_ticks(self, state):
        self.qt_viewer.viewer.scale_bar.ticks = state

    def _toggle_axes_visible(self, state):
        self.qt_viewer.viewer.axes.visible = state

    def _toggle_axes_colored(self, state):
        self.qt_viewer.viewer.axes.colored = state

    def _toggle_axes_labels(self, state):
        self.qt_viewer.viewer.axes.labels = state

    def _toggle_axes_dashed(self, state):
        self.qt_viewer.viewer.axes.dashed = state

    def _toggle_axes_arrows(self, state):
        self.qt_viewer.viewer.axes.arrows = state

    def _toggle_fullscreen(self, event):
        """Toggle fullscreen mode."""
        if self._qt_window.isFullScreen():
            self._qt_window.showNormal()
        else:
            self._qt_window.showFullScreen()

    def _toggle_play(self, state):
        """Toggle play."""
        if self.qt_viewer.dims.is_playing:
            self.qt_viewer.dims.stop()
        else:
            axis = self.qt_viewer.viewer.dims.last_used or 0
            self.qt_viewer.dims.play(axis)

    def add_plugin_dock_widget(
        self, plugin_name: str, widget_name: str = None
    ):
        """Add plugin dock widget if not already added.

        Parameters
        ----------
        plugin_name : str
            Name of a plugin providing a widget
        widget_name : str, optional
            Name of a widget provided by `plugin_name`. If `None`, and the
            specified plugin provides only a single widget, that widget will be
            returned, otherwise a ValueError will be raised, by default None
        """
        from ..viewer import Viewer

        Widget, dock_kwargs = plugins.get_plugin_widget(
            plugin_name, widget_name
        )
        if not widget_name:
            # if widget_name wasn't provided, `get_plugin_widget` will have
            # ensured that there is a single widget available.
            widget_name = list(plugins.dock_widgets[plugin_name])[0]

        full_name = plugins.menu_item_template.format(plugin_name, widget_name)
        if full_name in self._dock_widgets:
            self._dock_widgets[full_name].show()
            return

        # if the signature is looking a for a napari viewer, pass it.
        kwargs = {}
        for param in inspect.signature(Widget.__init__).parameters.values():
            if param.name == 'napari_viewer':
                kwargs['napari_viewer'] = self.qt_viewer.viewer
                break
            if param.annotation in ('napari.viewer.Viewer', Viewer):
                kwargs[param.name] = self.qt_viewer.viewer
                break
            # cannot look for param.kind == param.VAR_KEYWORD because
            # QWidget allows **kwargs but errs on unknown keyword arguments

        # instantiate the widget
        wdg = Widget(**kwargs)

        # Add dock widget
        self.add_dock_widget(
            wdg,
            name=full_name,
            area=dock_kwargs.get('area', 'right'),
            allowed_areas=dock_kwargs.get('allowed_areas', None),
        )

    def _add_plugin_function_widget(self, plugin_name: str, widget_name: str):
        """Add plugin function widget if not already added.

        Parameters
        ----------
        plugin_name : str
            Name of a plugin providing a widget
        widget_name : str, optional
            Name of a widget provided by `plugin_name`. If `None`, and the
            specified plugin provides only a single widget, that widget will be
            returned, otherwise a ValueError will be raised, by default None
        """
        full_name = plugins.menu_item_template.format(plugin_name, widget_name)
        if full_name in self._dock_widgets:
            self._dock_widgets[full_name].show()
            return

        func = plugins.function_widgets[plugin_name][widget_name]

        # Add function widget
        self.add_function_widget(
            func, name=full_name, area=None, allowed_areas=None
        )

    def add_dock_widget(
        self,
        widget: QWidget,
        *,
        name: str = '',
        area: str = 'bottom',
        allowed_areas=None,
        shortcut=None,
    ):
        """Convenience method to add a QDockWidget to the main window

        Parameters
        ----------
        widget : QWidget
            `widget` will be added as QDockWidget's main widget.
        name : str, optional
            Name of dock widget to appear in window menu.
        area : str
            Side of the main window to which the new dock widget will be added.
            Must be in {'left', 'right', 'top', 'bottom'}
        allowed_areas : list[str], optional
            Areas, relative to main window, that the widget is allowed dock.
            Each item in list must be in {'left', 'right', 'top', 'bottom'}
            By default, all areas are allowed.
        shortcut : str, optional
            Keyboard shortcut to appear in dropdown menu.

        Returns
        -------
        dock_widget : QtViewerDockWidget
            `dock_widget` that can pass viewer events.
        """

        dock_widget = QtViewerDockWidget(
            self.qt_viewer,
            widget,
            name=name,
            area=area,
            allowed_areas=allowed_areas,
            shortcut=shortcut,
        )
        self._add_viewer_dock_widget(dock_widget)

        if hasattr(widget, 'reset_choices'):
            # Keep the dropdown menus in the widget in sync with the layer model
            # if widget has a `reset_choices`, which is true for all magicgui
            # `CategoricalWidget`s
            layers_events = self.qt_viewer.viewer.layers.events
            layers_events.inserted.connect(widget.reset_choices)
            layers_events.removed.connect(widget.reset_choices)
            layers_events.reordered.connect(widget.reset_choices)

        # Add dock widget to dictionary
        self._dock_widgets[dock_widget.name] = dock_widget

        return dock_widget

    def _add_viewer_dock_widget(
        self, dock_widget: QtViewerDockWidget, tabify=False
    ):
        """Add a QtViewerDockWidget to the main window

        If other widgets already present in area then will tabify.

        Parameters
        ----------
        dock_widget : QtViewerDockWidget
            `dock_widget` will be added to the main window.
        tabify : bool
            Flag to tabify dockwidget or not.
        """
        # Find if any othe dock widgets are currently in area
        current_dws_in_area = []
        for dw in self._qt_window.findChildren(QDockWidget):
            if self._qt_window.dockWidgetArea(dw) == dock_widget.qt_area:
                current_dws_in_area.append(dw)

        self._qt_window.addDockWidget(dock_widget.qt_area, dock_widget)

        # If another dock widget present in area then tabify
        if len(current_dws_in_area) > 0 and tabify:
            self._qt_window.tabifyDockWidget(
                current_dws_in_area[-1], dock_widget
            )
            dock_widget.show()
            dock_widget.raise_()

        action = dock_widget.toggleViewAction()
        action.setStatusTip(dock_widget.name)
        action.setText(dock_widget.name)
        if dock_widget.shortcut is not None:
            action.setShortcut(dock_widget.shortcut)
        self.window_menu.addAction(action)

    def remove_dock_widget(self, widget: QWidget):
        """Removes specified dock widget.

        If a QDockWidget is not provided, the existing QDockWidgets will be
        searched for one whose inner widget (``.widget()``) is the provided
        ``widget``.

        Parameters
        ----------
        widget : QWidget | str
            If widget == 'all', all docked widgets will be removed.
        """
        if widget == 'all':
            for dw in list(self._dock_widgets.values()):
                self.remove_dock_widget(dw)
            return

        if not isinstance(widget, QDockWidget):
            for dw in self._qt_window.findChildren(QDockWidget):
                if dw.widget() is widget:
                    _dw: QDockWidget = dw
                    break
            else:
                raise LookupError(
                    trans._(
                        "Could not find a dock widget containing: {widget}",
                        deferred=True,
                        widget=widget,
                    )
                )
        else:
            _dw = widget

        if _dw.widget():
            _dw.widget().setParent(None)
        self._qt_window.removeDockWidget(_dw)
        self.window_menu.removeAction(_dw.toggleViewAction())

        # Remove dock widget from dictionary
        del self._dock_widgets[_dw.name]

        # Deleting the dock widget means any references to it will no longer
        # work but it's not really useful anyway, since the inner widget has
        # been removed. and anyway: people should be using add_dock_widget
        # rather than directly using _add_viewer_dock_widget
        _dw.deleteLater()

    def add_function_widget(
        self,
        function,
        *,
        magic_kwargs=None,
        name: str = '',
        area=None,
        allowed_areas=None,
        shortcut=None,
    ):
        """Turn a function into a dock widget via magicgui.

        Parameters
        ----------
        function : callable
            Function that you want to add.
        magic_kwargs : dict, optional
            Keyword arguments to :func:`magicgui.magicgui` that
            can be used to specify widget.
        name : str, optional
            Name of dock widget to appear in window menu.
        area : str, optional
            Side of the main window to which the new dock widget will be added.
            Must be in {'left', 'right', 'top', 'bottom'}. If not provided the
            default will be determined by the widget.layout, with 'vertical'
            layouts appearing on the right, otherwise on the bottom.
        allowed_areas : list[str], optional
            Areas, relative to main window, that the widget is allowed dock.
            Each item in list must be in {'left', 'right', 'top', 'bottom'}
            By default, only provided areas is allowed.
        shortcut : str, optional
            Keyboard shortcut to appear in dropdown menu.

        Returns
        -------
        dock_widget : QtViewerDockWidget
            `dock_widget` that can pass viewer events.
        """
        from magicgui import magicgui

        if magic_kwargs is None:
            magic_kwargs = {
                'auto_call': False,
                'call_button': "run",
                'layout': 'vertical',
            }

        widget = magicgui(function, **magic_kwargs or {})

        if area is None:
            if str(widget.layout) == 'vertical':
                area = 'right'
            else:
                area = 'bottom'

        if allowed_areas is None:
            allowed_areas = [area]

        return self.add_dock_widget(
            widget,
            name=name or function.__name__.replace('_', ' '),
            area=area,
            allowed_areas=allowed_areas,
            shortcut=shortcut,
        )

    def resize(self, width, height):
        """Resize the window.

        Parameters
        ----------
        width : int
            Width in logical pixels.
        height : int
            Height in logical pixels.
        """
        self._qt_window.resize(width, height)

    def show(self):
        """Resize, show, and bring forward the window.

        Raises
        ------
        RuntimeError
            If the viewer.window has already been closed and deleted.
        """
        try:
            self._qt_window.show()
        except (AttributeError, RuntimeError):
            raise RuntimeError(
                trans._(
                    "This viewer has already been closed and deleted. "
                    "Please create a new one."
                )
            )

        if SETTINGS.application.first_time:
            SETTINGS.application.first_time = False
            try:
                self._qt_window.resize(self._qt_window.layout().sizeHint())
            except (AttributeError, RuntimeError):
                raise RuntimeError(
                    trans._(
                        "This viewer has already been closed and deleted. "
                        "Please create a new one."
                    )
                )
        else:
            try:
                if SETTINGS.application.save_window_geometry:
                    self._qt_window._set_window_settings(
                        *self._qt_window._load_window_settings()
                    )
            except Exception as err:
                import warnings

                warnings.warn(
                    trans._(
                        "The window geometry settings could not be "
                        "loaded due to the following error: {err}",
                        deferred=True,
                        err=err,
                    ),
                    category=RuntimeWarning,
                    stacklevel=2,
                )

        # Resize axis labels now that window is shown
        self.qt_viewer.dims._resize_axis_labels()

        # We want to bring the viewer to the front when
        # A) it is our own event loop OR we are running in jupyter
        # B) it is not the first time a QMainWindow is being created

        # `app_name` will be "napari" iff the application was instantiated in
        # get_app(). isActiveWindow() will be True if it is the second time a
        # _qt_window has been created.
        # See #721, #732, #735, #795, #1594
        app_name = QApplication.instance().applicationName()
        if (
            app_name == 'napari' or in_jupyter()
        ) and self._qt_window.isActiveWindow():
            self.activate()

    def activate(self):
        """Make the viewer the currently active window."""
        self._qt_window.raise_()  # for macOS
        self._qt_window.activateWindow()  # for Windows

    def _update_theme(self, event=None):
        """Update widget color theme."""
        if event:
            value = event.value
            SETTINGS.appearance.theme = value
            self.qt_viewer.viewer.theme = value
        else:
            value = self.qt_viewer.viewer.theme

        try:
            self._qt_window.setStyleSheet(get_stylesheet(value))
        except AttributeError:
            pass

    def _status_changed(self, event):
        """Update status bar.

        Parameters
        ----------
        event : napari.utils.event.Event
            The napari event that triggered this method.
        """
        self._status_bar.showMessage(event.value)

    def _title_changed(self, event):
        """Update window title.

        Parameters
        ----------
        event : napari.utils.event.Event
            The napari event that triggered this method.
        """
        self._qt_window.setWindowTitle(event.value)

    def _help_changed(self, event):
        """Update help message on status bar.

        Parameters
        ----------
        event : napari.utils.event.Event
            The napari event that triggered this method.
        """
        self._help.setText(event.value)

    def _screenshot_dialog(self):
        """Save screenshot of current display with viewer, default .png"""
        dial = ScreenshotDialog(
            self.screenshot, self.qt_viewer, self.qt_viewer._last_visited_dir
        )
        if dial.exec_():
            self._last_visited_dir = os.path.dirname(dial.selectedFiles()[0])

    def _restart(self):
        """Restart the napari application."""
        self._qt_window.restart()

    def screenshot(self, path=None):
        """Take currently displayed viewer and convert to an image array.

        Parameters
        ----------
        path : str
            Filename for saving screenshot image.

        Returns
        -------
        image : array
            Numpy array of type ubyte and shape (h, w, 4). Index [0, 0] is the
            upper-left corner of the rendered region.
        """
        img = self._qt_window.grab().toImage()
        if path is not None:
            imsave(path, QImg2array(img))  # scikit-image imsave method
        return QImg2array(img)

    def close(self):
        """Close the viewer window and cleanup sub-widgets."""
        # Someone is closing us twice? Only try to delete self._qt_window
        # if we still have one.
        if hasattr(self, '_qt_window'):
            self.qt_viewer.close()
            self._qt_window.close()
            del self._qt_window
