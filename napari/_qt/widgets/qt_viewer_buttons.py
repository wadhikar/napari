from qtpy.QtWidgets import QFrame, QHBoxLayout, QPushButton

from ...utils.interactions import KEY_SYMBOLS
from ...utils.translations import trans


class QtLayerButtons(QFrame):
    """Button controls for napari layers.

    Parameters
    ----------
    viewer : napari.components.ViewerModel
        Napari viewer containing the rendered scene, layers, and controls.

    Attributes
    ----------
    deleteButton : QtDeleteButton
        Button to delete selected layers.
    newLabelsButton : QtViewerPushButton
        Button to add new Label layer.
    newPointsButton : QtViewerPushButton
        Button to add new Points layer.
    newShapesButton : QtViewerPushButton
        Button to add new Shapes layer.
    viewer : napari.components.ViewerModel
        Napari viewer containing the rendered scene, layers, and controls.
    """

    def __init__(self, viewer):
        super().__init__()

        self.viewer = viewer
        self.deleteButton = QtDeleteButton(self.viewer)
        self.newPointsButton = QtViewerPushButton(
            self.viewer,
            'new_points',
            trans._('New points layer'),
            lambda: self.viewer.add_points(
                ndim=max(self.viewer.dims.ndim, 2),
                scale=self.viewer.layers.extent.step,
            ),
        )

        self.newShapesButton = QtViewerPushButton(
            self.viewer,
            'new_shapes',
            trans._('New shapes layer'),
            lambda: self.viewer.add_shapes(
                ndim=max(self.viewer.dims.ndim, 2),
                scale=self.viewer.layers.extent.step,
            ),
        )
        self.newLabelsButton = QtViewerPushButton(
            self.viewer,
            'new_labels',
            trans._('New labels layer'),
            lambda: self.viewer._new_labels(),
        )

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.newPointsButton)
        layout.addWidget(self.newShapesButton)
        layout.addWidget(self.newLabelsButton)
        layout.addStretch(0)
        layout.addWidget(self.deleteButton)
        self.setLayout(layout)


class QtViewerButtons(QFrame):
    """Button controls for the napari viewer.

    Parameters
    ----------
    viewer : napari.components.ViewerModel
        Napari viewer containing the rendered scene, layers, and controls.

    Attributes
    ----------
    consoleButton : QtViewerPushButton
        Button to open iPython console within napari.
    rollDimsButton : QtViewerPushButton
        Button to roll orientation of spatial dimensions in the napari viewer.
    transposeDimsButton : QtViewerPushButton
        Button to transpose dimensions in the napari viewer.
    resetViewButton : QtViewerPushButton
        Button resetting the view of the rendered scene.
    gridViewButton : QtStateButton
        Button to toggle grid view mode of layers on and off.
    ndisplayButton : QtStateButton
        Button to toggle number of displayed dimensions.
    viewer : napari.components.ViewerModel
        Napari viewer containing the rendered scene, layers, and controls.
    """

    def __init__(self, viewer):
        super().__init__()

        self.viewer = viewer
        self.consoleButton = QtViewerPushButton(
            self.viewer,
            'console',
            trans._(
                "Open IPython terminal ({key1}-{key2}-C)",
                key1=KEY_SYMBOLS['Control'],
                key2=KEY_SYMBOLS['Shift'],
            ),
        )
        self.consoleButton.setProperty('expanded', False)
        self.rollDimsButton = QtViewerPushButton(
            self.viewer,
            'roll',
            trans._(
                "Roll dimensions order for display ({key}-E)",
                key=KEY_SYMBOLS['Control'],
            ),
            lambda: self.viewer.dims._roll(),
        )
        self.transposeDimsButton = QtViewerPushButton(
            self.viewer,
            'transpose',
            trans._(
                "Transpose displayed dimensions ({key}-T)",
                key=KEY_SYMBOLS['Control'],
            ),
            lambda: self.viewer.dims._transpose(),
        )
        self.resetViewButton = QtViewerPushButton(
            self.viewer,
            'home',
            trans._("Reset view ({key}-R)", key=KEY_SYMBOLS['Control']),
            lambda: self.viewer.reset_view(),
        )

        self.gridViewButton = QtStateButton(
            'grid_view_button',
            self.viewer.grid,
            'enabled',
            self.viewer.grid.events,
        )
        self.gridViewButton.setToolTip(
            trans._("Toggle grid view ({key}-G)", key=KEY_SYMBOLS['Control'])
        )

        self.ndisplayButton = QtStateButton(
            "ndisplay_button",
            self.viewer.dims,
            'ndisplay',
            self.viewer.dims.events.ndisplay,
            2,
            3,
        )
        self.ndisplayButton.setToolTip(
            trans._(
                "Toggle number of displayed dimensions ({key}-Y)",
                key=KEY_SYMBOLS['Control'],
            )
        )

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.consoleButton)
        layout.addWidget(self.ndisplayButton)
        layout.addWidget(self.rollDimsButton)
        layout.addWidget(self.transposeDimsButton)
        layout.addWidget(self.gridViewButton)
        layout.addWidget(self.resetViewButton)
        layout.addStretch(0)
        self.setLayout(layout)


class QtDeleteButton(QPushButton):
    """Delete button to remove selected layers.

    Parameters
    ----------
    viewer : napari.components.ViewerModel
        Napari viewer containing the rendered scene, layers, and controls.

    Attributes
    ----------
    hover : bool
        Hover is true while mouse cursor is on the button widget.
    viewer : napari.components.ViewerModel
        Napari viewer containing the rendered scene, layers, and controls.
    """

    def __init__(self, viewer):
        super().__init__()

        self.viewer = viewer
        self.setToolTip(
            trans._(
                "Delete selected layers ({key1}-{key2})",
                key1=KEY_SYMBOLS['Control'],
                key2=KEY_SYMBOLS['Backspace'],
            )
        )
        self.setAcceptDrops(True)
        self.clicked.connect(lambda: self.viewer.layers.remove_selected())

    def dragEnterEvent(self, event):
        """The cursor enters the widget during a drag and drop operation.

        Parameters
        ----------
        event : qtpy.QtCore.QEvent
            Event from the Qt context.
        """
        event.accept()
        self.hover = True
        self.update()

    def dragLeaveEvent(self, event):
        """The cursor leaves the widget during a drag and drop operation.

        Using event.ignore() here allows the event to pass through the
        parent widget to its child widget, otherwise the parent widget
        would catch the event and not pass it on to the child widget.

        Parameters
        ----------
        event : qtpy.QtCore.QEvent
            Event from the Qt context.
        """
        event.ignore()
        self.hover = False
        self.update()

    def dropEvent(self, event):
        """The drag and drop mouse event is completed.

        Parameters
        ----------
        event : qtpy.QtCore.QEvent
            Event from the Qt context.
        """
        event.accept()
        layer_name = event.mimeData().text()
        layer = self.viewer.layers[layer_name]
        if not layer.selected:
            self.viewer.layers.remove(layer)
        else:
            self.viewer.layers.remove_selected()


class QtViewerPushButton(QPushButton):
    """Push button.

    Parameters
    ----------
    viewer : napari.components.ViewerModel
        Napari viewer containing the rendered scene, layers, and controls.

    Attributes
    ----------
    viewer : napari.components.ViewerModel
        Napari viewer containing the rendered scene, layers, and controls.
    """

    def __init__(self, viewer, button_name, tooltip=None, slot=None):
        super().__init__()

        self.viewer = viewer
        self.setToolTip(tooltip or button_name)
        self.setProperty('mode', button_name)
        if slot is not None:
            self.clicked.connect(slot)


class QtStateButton(QtViewerPushButton):
    """Button to toggle between two states.

    Parameters
    ----------
    button_name : str
        A string that will be used in qss to style the button with the
        QtStateButton[mode=...] selector,
    target : object
        object on which you want to change the property when button pressed.
    attribute:
        name of attribute on `object` you wish to change.
    events: EventEmitter
        event emitter that will trigger when value is changed
    onstate: Any
        value to use for ``setattr(object, attribute, onstate)`` when clicking
        this button
    offstate: Any
        value to use for ``setattr(object, attribute, offstate)`` when clicking
        this button.
    """

    def __init__(
        self,
        button_name,
        target,
        attribute,
        events,
        onstate=True,
        offstate=False,
    ):
        super().__init__(target, button_name)
        self.setCheckable(True)

        self._target = target
        self._attribute = attribute
        self._onstate = onstate
        self._offstate = offstate
        self._events = events
        self._events.connect(self._on_change)
        self.clicked.connect(self.change)
        self._on_change()

    def change(self):
        """Toggle between the multiple states of this button."""
        if self.isChecked():
            newstate = self._onstate
        else:
            newstate = self._offstate
        setattr(self._target, self._attribute, newstate)

    def _on_change(self, event=None):
        """Called wen mirrored value changes

        Parameters
        ----------
        event : qtpy.QtCore.QEvent
            Event from the Qt context.
        """
        with self._events.blocker():
            if self.isChecked() != (
                getattr(self._target, self._attribute) == self._onstate
            ):
                self.toggle()
