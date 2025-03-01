import warnings
from contextlib import contextmanager
from copy import copy, deepcopy
from itertools import cycle
from typing import Dict, Optional, Tuple, Union

import numpy as np
from vispy.color import get_color_names

from ...utils.colormaps import Colormap, ValidColormapArg, ensure_colormap
from ...utils.colormaps.standardize_color import (
    hex_to_name,
    rgb_to_hex,
    transform_color,
)
from ...utils.events import Event
from ...utils.misc import ensure_iterable
from ...utils.translations import trans
from ..base import Layer
from ..utils.color_manager_utils import guess_continuous, map_property
from ..utils.color_transformations import (
    ColorType,
    normalize_and_broadcast_colors,
    transform_color_cycle,
    transform_color_with_defaults,
)
from ..utils.layer_utils import dataframe_to_properties
from ..utils.text import TextManager
from ._shape_list import ShapeList
from ._shapes_constants import (
    BACKSPACE,
    Box,
    ColorMode,
    Mode,
    ShapeType,
    shape_classes,
)
from ._shapes_mouse_bindings import (
    add_ellipse,
    add_line,
    add_path_polygon,
    add_path_polygon_creating,
    add_rectangle,
    highlight,
    select,
    vertex_insert,
    vertex_remove,
)
from ._shapes_utils import (
    create_box,
    extract_shape_type,
    get_shape_ndim,
    number_of_shapes,
)

DEFAULT_COLOR_CYCLE = np.array([[1, 0, 1, 1], [0, 1, 0, 1]])


class Shapes(Layer):
    """Shapes layer.

    Parameters
    ----------
    data : list or array
        List of shape data, where each element is an (N, D) array of the
        N vertices of a shape in D dimensions. Can be an 3-dimensional
        array if each shape has the same number of vertices.
    ndim : int
        Number of dimensions for shapes. When data is not None, ndim must be D.
        An empty shapes layer can be instantiated with arbitrary ndim.
    properties : dict {str: array (N,)}, DataFrame
        Properties for each shape. Each property should be an array of length N,
        where N is the number of shapes.
    text : str, dict
        Text to be displayed with the shapes. If text is set to a key in properties,
        the value of that property will be displayed. Multiple properties can be
        composed using f-string-like syntax (e.g., '{property_1}, {float_property:.2f}).
        A dictionary can be provided with keyword arguments to set the text values
        and display properties. See TextManager.__init__() for the valid keyword arguments.
        For example usage, see /napari/examples/add_shapes_with_text.py.
    shape_type : string or list
        String of shape shape_type, must be one of "{'line', 'rectangle',
        'ellipse', 'path', 'polygon'}". If a list is supplied it must be
        the same length as the length of `data` and each element will be
        applied to each shape otherwise the same value will be used for all
        shapes.
    edge_width : float or list
        Thickness of lines and edges. If a list is supplied it must be the
        same length as the length of `data` and each element will be
        applied to each shape otherwise the same value will be used for all
        shapes.
    edge_color : str, array-like
        If string can be any color name recognized by vispy or hex value if
        starting with `#`. If array-like must be 1-dimensional array with 3
        or 4 elements. If a list is supplied it must be the same length as
        the length of `data` and each element will be applied to each shape
        otherwise the same value will be used for all shapes.
    edge_color_cycle : np.ndarray, list
        Cycle of colors (provided as string name, RGB, or RGBA) to map to edge_color if a
        categorical attribute is used color the vectors.
    edge_colormap : str, napari.utils.Colormap
        Colormap to set edge_color if a continuous attribute is used to set face_color.
    edge_contrast_limits : None, (float, float)
        clims for mapping the property to a color map. These are the min and max value
        of the specified property that are mapped to 0 and 1, respectively.
        The default value is None. If set the none, the clims will be set to
        (property.min(), property.max())
    face_color : str, array-like
        If string can be any color name recognized by vispy or hex value if
        starting with `#`. If array-like must be 1-dimensional array with 3
        or 4 elements. If a list is supplied it must be the same length as
        the length of `data` and each element will be applied to each shape
        otherwise the same value will be used for all shapes.
    face_color_cycle : np.ndarray, list
        Cycle of colors (provided as string name, RGB, or RGBA) to map to face_color if a
        categorical attribute is used color the vectors.
    face_colormap : str, napari.utils.Colormap
        Colormap to set face_color if a continuous attribute is used to set face_color.
    face_contrast_limits : None, (float, float)
        clims for mapping the property to a color map. These are the min and max value
        of the specified property that are mapped to 0 and 1, respectively.
        The default value is None. If set the none, the clims will be set to
        (property.min(), property.max())
    z_index : int or list
        Specifier of z order priority. Shapes with higher z order are
        displayed ontop of others. If a list is supplied it must be the
        same length as the length of `data` and each element will be
        applied to each shape otherwise the same value will be used for all
        shapes.
    name : str
        Name of the layer.
    metadata : dict
        Layer metadata.
    scale : tuple of float
        Scale factors for the layer.
    translate : tuple of float
        Translation values for the layer.
    rotate : float, 3-tuple of float, or n-D array.
        If a float convert into a 2D rotation matrix using that value as an
        angle. If 3-tuple convert into a 3D rotation matrix, using a yaw,
        pitch, roll convention. Otherwise assume an nD rotation. Angles are
        assumed to be in degrees. They can be converted from radians with
        np.degrees if needed.
    shear : 1-D array or n-D array
        Either a vector of upper triangular values, or an nD shear matrix with
        ones along the main diagonal.
    affine : n-D array or napari.utils.transforms.Affine
        (N+1, N+1) affine transformation matrix in homogeneous coordinates.
        The first (N, N) entries correspond to a linear transform and
        the final column is a lenght N translation vector and a 1 or a napari
        AffineTransform object. If provided then translate, scale, rotate, and
        shear values are ignored.
    opacity : float
        Opacity of the layer visual, between 0.0 and 1.0.
    blending : str
        One of a list of preset blending modes that determines how RGB and
        alpha values of the layer visual get mixed. Allowed values are
        {'opaque', 'translucent', and 'additive'}.
    visible : bool
        Whether the layer visual is currently being displayed.

    Attributes
    ----------
    data : (N, ) list of array
        List of shape data, where each element is an (N, D) array of the
        N vertices of a shape in D dimensions.
    properties : dict {str: array (N,)}, DataFrame
        Properties for each shape. Each property should be an array of length N,
        where N is the number of shapes.
    text : str, dict
        Text to be displayed with the shapes. If text is set to a key in properties,
        the value of that property will be displayed. Multiple properties can be
        composed using f-string-like syntax (e.g., '{property_1}, {float_property:.2f}).
        For example usage, see /napari/examples/add_shapes_with_text.py.
    shape_type : (N, ) list of str
        Name of shape type for each shape.
    edge_color : str, array-like
        Color of the shape border. Numeric color values should be RGB(A).
    face_color : str, array-like
        Color of the shape face. Numeric color values should be RGB(A).
    edge_width : (N, ) list of float
        Edge width for each shape.
    z_index : (N, ) list of int
        z-index for each shape.
    current_edge_width : float
        Thickness of lines and edges of the next shape to be added or the
        currently selected shape.
    current_edge_color : str
        Color of the edge of the next shape to be added or the currently
        selected shape.
    current_face_color : str
        Color of the face of the next shape to be added or the currently
        selected shape.
    selected_data : set
        List of currently selected shapes.
    nshapes : int
        Total number of shapes.
    mode : Mode
        Interactive mode. The normal, default mode is PAN_ZOOM, which
        allows for normal interactivity with the canvas.

        The SELECT mode allows for entire shapes to be selected, moved and
        resized.

        The DIRECT mode allows for shapes to be selected and their individual
        vertices to be moved.

        The VERTEX_INSERT and VERTEX_REMOVE modes allow for individual
        vertices either to be added to or removed from shapes that are already
        selected. Note that shapes cannot be selected in this mode.

        The ADD_RECTANGLE, ADD_ELLIPSE, ADD_LINE, ADD_PATH, and ADD_POLYGON
        modes all allow for their corresponding shape type to be added.

    Notes
    -----
    _data_dict : Dict of ShapeList
        Dictionary containing all the shape data indexed by slice tuple
    _data_view : ShapeList
        Object containing the currently viewed shape data.
    _mode_history : Mode
        Interactive mode captured on press of <space>.
    _selected_data_history : set
        Set of currently selected captured on press of <space>.
    _selected_data_stored : set
        Set of selected previously displayed. Used to prevent rerendering the
        same highlighted shapes when no data has changed.
    _selected_box : None | np.ndarray
        `None` if no shapes are selected, otherwise a 10x2 array of vertices of
        the interaction box. The first 8 points are the corners and midpoints
        of the box. The 9th point is the center of the box, and the last point
        is the location of the rotation handle that can be used to rotate the
        box.
    _drag_start : None | np.ndarray
        If a drag has been started and is in progress then a length 2 array of
        the initial coordinates of the drag. `None` otherwise.
    _drag_box : None | np.ndarray
        If a drag box is being created to select shapes then this is a 2x2
        array of the two extreme corners of the drag. `None` otherwise.
    _drag_box_stored : None | np.ndarray
        If a drag box is being created to select shapes then this is a 2x2
        array of the two extreme corners of the drag that have previously been
        rendered. `None` otherwise. Used to prevent rerendering the same
        drag box when no data has changed.
    _is_moving : bool
        Bool indicating if any shapes are currently being moved.
    _is_selecting : bool
        Bool indicating if a drag box is currently being created in order to
        select shapes.
    _is_creating : bool
        Bool indicating if any shapes are currently being created.
    _fixed_aspect : bool
        Bool indicating if aspect ratio of shapes should be preserved on
        resizing.
    _aspect_ratio : float
        Value of aspect ratio to be preserved if `_fixed_aspect` is `True`.
    _fixed_vertex : None | np.ndarray
        If a scaling or rotation is in progress then a length 2 array of the
        coordinates that are remaining fixed during the move. `None` otherwise.
    _fixed_index : int
        If a scaling or rotation is in progress then the index of the vertex of
        the boudning box that is remaining fixed during the move. `None`
        otherwise.
    _update_properties : bool
        Bool indicating if properties are to allowed to update the selected
        shapes when they are changed. Blocking this prevents circular loops
        when shapes are selected and the properties are changed based on that
        selection
    _allow_thumnail_update : bool
        Flag set to true to allow the thumbnail to be updated. Blocking the thumbnail
        can be advantageous where responsiveness is critical.
    _clipboard : dict
        Dict of shape objects that are to be used during a copy and paste.
    _colors : list
        List of supported vispy color names.
    _vertex_size : float
        Size of the vertices of the shapes and bounding box in Canvas
        coordinates.
    _rotation_handle_length : float
        Length of the rotation handle of the boudning box in Canvas
        coordinates.
    _input_ndim : int
        Dimensions of shape data.
    _thumbnail_update_thresh : int
        If there are more than this number of shapes, the thumnail
        won't update during interactive events
    """

    _colors = get_color_names()
    _vertex_size = 10
    _rotation_handle_length = 20
    _highlight_color = (0, 0.6, 1)
    _highlight_width = 1.5

    # If more shapes are present then they are randomly subsampled
    # in the thumbnail
    _max_shapes_thumbnail = 100

    def __init__(
        self,
        data=None,
        *,
        ndim=None,
        properties=None,
        text=None,
        shape_type='rectangle',
        edge_width=1,
        edge_color='black',
        edge_color_cycle=None,
        edge_colormap='viridis',
        edge_contrast_limits=None,
        face_color='white',
        face_color_cycle=None,
        face_colormap='viridis',
        face_contrast_limits=None,
        z_index=0,
        name=None,
        metadata=None,
        scale=None,
        translate=None,
        rotate=None,
        shear=None,
        affine=None,
        opacity=0.7,
        blending='translucent',
        visible=True,
    ):
        if data is None:
            if ndim is None:
                ndim = 2
            data = np.empty((0, 0, ndim))
        else:
            data, shape_type = extract_shape_type(data, shape_type)
            data_ndim = get_shape_ndim(data)
            if ndim is not None and ndim != data_ndim:
                raise ValueError(
                    trans._("Shape dimensions must be equal to ndim")
                )
            ndim = data_ndim

        super().__init__(
            data,
            ndim=ndim,
            name=name,
            metadata=metadata,
            scale=scale,
            translate=translate,
            rotate=rotate,
            shear=shear,
            affine=affine,
            opacity=opacity,
            blending=blending,
            visible=visible,
        )

        self.events.add(
            mode=Event,
            edge_width=Event,
            edge_color=Event,
            face_color=Event,
            properties=Event,
            current_edge_color=Event,
            current_face_color=Event,
            current_properties=Event,
            highlight=Event,
        )

        # Flag set to false to block thumbnail refresh
        self._allow_thumbnail_update = True

        self._display_order_stored = []
        self._ndisplay_stored = self._ndisplay

        # Save the properties
        if properties is None:
            self._properties = {}
            self._property_choices = {}
        elif len(data) > 0:
            properties, _ = dataframe_to_properties(properties)
            self._properties = self._validate_properties(properties, len(data))
            self._property_choices = {
                k: np.unique(v) for k, v in properties.items()
            }
        elif len(data) == 0:
            self._property_choices = {
                k: np.asarray(v) for k, v in properties.items()
            }
            empty_properties = {
                k: np.empty(0, dtype=v.dtype)
                for k, v in self._property_choices.items()
            }
            self._properties = empty_properties

        # make the text
        if text is None or isinstance(text, (list, np.ndarray, str)):
            self._text = TextManager(text, len(data), self.properties)
        elif isinstance(text, dict):
            copied_text = deepcopy(text)
            copied_text['properties'] = self.properties
            copied_text['n_text'] = len(data)
            self._text = TextManager(**copied_text)
        else:
            raise TypeError(trans._('text should be a string, array, or dict'))

        # The following shape properties are for the new shapes that will
        # be drawn. Each shape has a corresponding property with the
        # value for itself
        if np.isscalar(edge_width):
            self._current_edge_width = edge_width
        else:
            self._current_edge_width = 1

        self._data_view = ShapeList(ndisplay=self._ndisplay)
        self._data_view.slice_key = np.array(self._slice_indices)[
            list(self._dims_not_displayed)
        ]

        self._value = (None, None)
        self._value_stored = (None, None)
        self._moving_value = (None, None)
        self._selected_data = set()
        self._selected_data_stored = set()
        self._selected_data_history = set()
        self._selected_box = None

        self._drag_start = None
        self._fixed_vertex = None
        self._fixed_aspect = False
        self._aspect_ratio = 1
        self._is_moving = False
        # _moving_coordinates are needed for fixing aspect ratio during
        # a resize
        self._moving_coordinates = None
        self._fixed_index = 0
        self._is_selecting = False
        self._drag_box = None
        self._drag_box_stored = None
        self._is_creating = False
        self._clipboard = {}

        self._mode = Mode.PAN_ZOOM
        self._mode_history = self._mode
        self._status = self.mode
        self._help = trans._('enter a selection mode to edit shape properties')

        self._init_shapes(
            data,
            shape_type=shape_type,
            edge_width=edge_width,
            edge_color=edge_color,
            edge_color_cycle=edge_color_cycle,
            edge_colormap=edge_colormap,
            edge_contrast_limits=edge_contrast_limits,
            face_color=face_color,
            face_color_cycle=face_color_cycle,
            face_colormap=face_colormap,
            face_contrast_limits=face_contrast_limits,
            z_index=z_index,
        )

        # set the current_* properties
        if len(data) > 0:
            self._current_edge_color = self.edge_color[-1]
            self._current_face_color = self.face_color[-1]
            self.current_properties = {
                k: np.asarray([v[-1]]) for k, v in self.properties.items()
            }
        elif len(data) == 0 and self.properties:
            self.current_properties = {
                k: np.asarray([v[0]])
                for k, v in self._property_choices.items()
            }
            self._initialize_current_color_for_empty_layer(edge_color, 'edge')
            self._initialize_current_color_for_empty_layer(face_color, 'face')
        elif len(data) == 0 and len(self.properties) == 0:
            self._current_edge_color = transform_color_with_defaults(
                num_entries=1,
                colors=edge_color,
                elem_name="edge_color",
                default="black",
            )
            self._current_face_color = transform_color_with_defaults(
                num_entries=1,
                colors=face_color,
                elem_name="face_color",
                default="black",
            )
            self.current_properties = {}

        # Trigger generation of view slice and thumbnail
        self._update_dims()

    def _initialize_current_color_for_empty_layer(
        self, color: ColorType, attribute: str
    ):
        """Initialize current_{edge,face}_color when starting with empty layer.

        Parameters
        ----------
        color : (N, 4) array or str
            The value for setting edge or face_color
        attribute : str in {'edge', 'face'}
            The name of the attribute to set the color of.
            Should be 'edge' for edge_color or 'face' for face_color.
        """
        color_mode = getattr(self, f'_{attribute}_color_mode')
        if color_mode == ColorMode.DIRECT:
            curr_color = transform_color_with_defaults(
                num_entries=1,
                colors=color,
                elem_name=f'{attribute}_color',
                default="white",
            )

        elif color_mode == ColorMode.CYCLE:
            color_cycle = getattr(self, f'_{attribute}_color_cycle')
            curr_color = transform_color(next(color_cycle))

            # add the new color cycle mapping
            color_property = getattr(self, f'_{attribute}_color_property')
            prop_value = self._property_choices[color_property][0]
            color_cycle_map = getattr(self, f'{attribute}_color_cycle_map')
            color_cycle_map[prop_value] = np.squeeze(curr_color)
            setattr(self, f'{attribute}_color_cycle_map', color_cycle_map)

        elif color_mode == ColorMode.COLORMAP:
            color_property = getattr(self, f'_{attribute}_color_property')
            prop_value = self._property_choices[color_property][0]
            colormap = getattr(self, f'{attribute}_colormap')
            contrast_limits = getattr(self, f'_{attribute}_contrast_limits')
            curr_color, _ = map_property(
                prop=prop_value,
                colormap=colormap,
                contrast_limits=contrast_limits,
            )
        setattr(self, f'_current_{attribute}_color', curr_color)

    @property
    def data(self):
        """list: Each element is an (N, D) array of the vertices of a shape."""
        return self._data_view.data

    @data.setter
    def data(self, data):
        self._finish_drawing()

        data, shape_type = extract_shape_type(data)
        n_new_shapes = number_of_shapes(data)
        # not given a shape_type through data
        if shape_type is None:
            shape_type = self.shape_type

        edge_widths = self._data_view.edge_widths
        edge_color = self._data_view.edge_color
        face_color = self._data_view.face_color
        z_indices = self._data_view.z_indices

        # fewer shapes, trim attributes
        if self.nshapes > n_new_shapes:
            shape_type = shape_type[:n_new_shapes]
            edge_widths = edge_widths[:n_new_shapes]
            z_indices = z_indices[:n_new_shapes]
            edge_color = edge_color[:n_new_shapes]
            face_color = face_color[:n_new_shapes]
        # more shapes, add attributes
        elif self.nshapes < n_new_shapes:
            n_shapes_difference = n_new_shapes - self.nshapes
            shape_type = shape_type + ["rectangle"] * n_shapes_difference
            edge_widths = edge_widths + [1] * n_shapes_difference
            z_indices = z_indices + [0] * n_shapes_difference
            edge_color = np.concatenate(
                (
                    edge_color,
                    self._get_new_shape_color(n_shapes_difference, 'edge'),
                )
            )
            face_color = np.concatenate(
                (
                    face_color,
                    self._get_new_shape_color(n_shapes_difference, 'face'),
                )
            )

        self._data_view = ShapeList()
        self.add(
            data,
            shape_type=shape_type,
            edge_width=edge_widths,
            edge_color=edge_color,
            face_color=face_color,
            z_index=z_indices,
        )

        self._update_dims()
        self.events.data(value=self.data)
        self._set_editable()

    def _on_selection(self, selected: bool):
        # this method is slated for removal.  don't add anything new.
        if not selected:
            self._finish_drawing()

    @property
    def properties(self) -> Dict[str, np.ndarray]:
        """dict {str: np.ndarray (N,)}, DataFrame: Annotations for each shape"""
        return self._properties

    @properties.setter
    def properties(self, properties: Dict[str, np.ndarray]):
        if not isinstance(properties, dict):
            properties, _ = dataframe_to_properties(properties)
        self._properties = self._validate_properties(properties)
        if self._face_color_property and (
            self._face_color_property not in self._properties
        ):
            self._face_color_property = ''
            warnings.warn(
                'property used for face_color dropped', RuntimeWarning
            )

        if self._edge_color_property and (
            self._edge_color_property not in self._properties
        ):
            self._edge_color_property = ''
            warnings.warn(
                'property used for edge_color dropped', RuntimeWarning
            )

        if self.text.values is not None:
            self.refresh_text()
        self.events.properties()

    def _get_ndim(self):
        """Determine number of dimensions of the layer."""
        if self.nshapes == 0:
            ndim = self.ndim
        else:
            ndim = self.data[0].shape[1]
        return ndim

    @property
    def _extent_data(self) -> np.ndarray:
        """Extent of layer in data coordinates.

        Returns
        -------
        extent_data : array, shape (2, D)
        """
        if len(self.data) == 0:
            extrema = np.full((2, self.ndim), np.nan)
        else:
            maxs = np.max([np.max(d, axis=0) for d in self.data], axis=0)
            mins = np.min([np.min(d, axis=0) for d in self.data], axis=0)
            extrema = np.vstack([mins, maxs])
        return extrema

    @property
    def nshapes(self):
        """int: Total number of shapes."""
        return len(self._data_view.shapes)

    @property
    def current_edge_width(self):
        """float: Width of shape edges including lines and paths."""
        return self._current_edge_width

    @current_edge_width.setter
    def current_edge_width(self, edge_width):
        self._current_edge_width = edge_width
        if self._update_properties:
            for i in self.selected_data:
                self._data_view.update_edge_width(i, edge_width)
        self.events.edge_width()

    @property
    def current_edge_color(self):
        """str: color of shape edges including lines and paths."""
        hex_ = rgb_to_hex(self._current_edge_color)[0]
        return hex_to_name.get(hex_, hex_)

    @current_edge_color.setter
    def current_edge_color(self, edge_color):
        self._current_edge_color = transform_color(edge_color)
        if self._update_properties:
            for i in self.selected_data:
                self._data_view.update_edge_color(i, self._current_edge_color)
            self.events.edge_color()
            self._update_thumbnail()
        self.events.current_edge_color()

    @property
    def current_face_color(self):
        """str: color of shape faces."""
        hex_ = rgb_to_hex(self._current_face_color)[0]
        return hex_to_name.get(hex_, hex_)

    @current_face_color.setter
    def current_face_color(self, face_color):
        self._current_face_color = transform_color(face_color)
        if self._update_properties:
            for i in self.selected_data:
                self._data_view.update_face_color(i, self._current_face_color)
            self.events.face_color()
            self._update_thumbnail()
        self.events.current_face_color()

    @property
    def current_properties(self) -> Dict[str, np.ndarray]:
        """dict{str: np.ndarray(1,)}: properties for the next added shape."""
        return self._current_properties

    @current_properties.setter
    def current_properties(self, current_properties):
        self._current_properties = current_properties

        if (
            self._update_properties
            and len(self.selected_data) > 0
            and self._mode in [Mode.SELECT, Mode.PAN_ZOOM]
        ):
            props = self.properties
            for k in props:
                props[k][list(self.selected_data)] = current_properties[k]
            self.properties = props

            self.refresh_colors()
        self.events.current_properties()

    @property
    def shape_type(self):
        """list of str: name of shape type for each shape."""
        return self._data_view.shape_types

    @shape_type.setter
    def shape_type(self, shape_type):
        self._finish_drawing()

        new_data_view = ShapeList()
        shape_inputs = zip(
            self._data_view.data,
            ensure_iterable(shape_type),
            self._data_view.edge_widths,
            self._data_view.edge_color,
            self._data_view.face_color,
            self._data_view.z_indices,
        )

        self._add_shapes_to_view(shape_inputs, new_data_view)

        self._data_view = new_data_view
        self._update_dims()

    @property
    def edge_color(self):
        """(N x 4) np.ndarray: Array of RGBA face colors for each shape"""
        return self._data_view.edge_color

    @edge_color.setter
    def edge_color(self, edge_color):
        self._set_color(edge_color, 'edge')
        self.events.edge_color()
        self._update_thumbnail()

    @property
    def edge_color_cycle(self) -> np.ndarray:
        """Union[list, np.ndarray] :  Color cycle for edge_color.

        Can be a list of colors defined by name, RGB or RGBA
        """
        return self._edge_color_cycle_values

    @edge_color_cycle.setter
    def edge_color_cycle(self, edge_color_cycle: Union[list, np.ndarray]):
        self._set_color_cycle(edge_color_cycle, 'edge')

    @property
    def edge_colormap(self) -> Tuple[str, Colormap]:
        """Return the colormap to be applied to a property to get the edge color.

        Returns
        -------
        colormap : napari.utils.Colormap
            The Colormap object.
        """
        return self._edge_colormap

    @edge_colormap.setter
    def edge_colormap(self, colormap: ValidColormapArg):
        self._edge_colormap = ensure_colormap(colormap)

    @property
    def edge_contrast_limits(self) -> Tuple[float, float]:
        """None, (float, float): contrast limits for mapping
        the edge_color colormap property to 0 and 1
        """
        return self._edge_contrast_limits

    @edge_contrast_limits.setter
    def edge_contrast_limits(
        self, contrast_limits: Union[None, Tuple[float, float]]
    ):
        self._edge_contrast_limits = contrast_limits

    @property
    def edge_color_mode(self) -> str:
        """str: Edge color setting mode

        DIRECT (default mode) allows each shape color to be set arbitrarily

        CYCLE allows the color to be set via a color cycle over an attribute

        COLORMAP allows color to be set via a color map over an attribute
        """
        return str(self._edge_color_mode)

    @edge_color_mode.setter
    def edge_color_mode(self, edge_color_mode: Union[str, ColorMode]):
        self._set_color_mode(edge_color_mode, 'edge')

    @property
    def face_color(self):
        """(N x 4) np.ndarray: Array of RGBA face colors for each shape"""
        return self._data_view.face_color

    @face_color.setter
    def face_color(self, face_color):
        self._set_color(face_color, 'face')
        self.events.face_color()
        self._update_thumbnail()

    @property
    def face_color_cycle(self) -> np.ndarray:
        """Union[np.ndarray, cycle]:  Color cycle for face_color
        Can be a list of colors defined by name, RGB or RGBA
        """
        return self._face_color_cycle_values

    @face_color_cycle.setter
    def face_color_cycle(self, face_color_cycle: Union[np.ndarray, cycle]):
        self._set_color_cycle(face_color_cycle, 'face')

    @property
    def face_colormap(self) -> Tuple[str, Colormap]:
        """Return the colormap to be applied to a property to get the face color.

        Returns
        -------
        colormap : napari.utils.Colormap
            The Colormap object.
        """
        return self._face_colormap

    @face_colormap.setter
    def face_colormap(self, colormap: ValidColormapArg):
        self._face_colormap = ensure_colormap(colormap)

    @property
    def face_contrast_limits(self) -> Union[None, Tuple[float, float]]:
        """None, (float, float) : clims for mapping the face_color
        colormap property to 0 and 1
        """
        return self._face_contrast_limits

    @face_contrast_limits.setter
    def face_contrast_limits(
        self, contrast_limits: Union[None, Tuple[float, float]]
    ):
        self._face_contrast_limits = contrast_limits

    @property
    def face_color_mode(self) -> str:
        """str: Face color setting mode

        DIRECT (default mode) allows each shape color to be set arbitrarily

        CYCLE allows the color to be set via a color cycle over an attribute

        COLORMAP allows color to be set via a color map over an attribute
        """
        return str(self._face_color_mode)

    @face_color_mode.setter
    def face_color_mode(self, face_color_mode):
        self._set_color_mode(face_color_mode, 'face')

    def _set_color_mode(
        self, color_mode: Union[ColorMode, str], attribute: str
    ):
        """Set the face_color_mode or edge_color_mode property

        Parameters
        ----------
        color_mode : str, ColorMode
            The value for setting edge or face_color_mode. If color_mode is a string,
            it should be one of: 'direct', 'cycle', or 'colormap'
        attribute : str in {'edge', 'face'}
            The name of the attribute to set the color of.
            Should be 'edge' for edge_colo_moder or 'face' for face_color_mode.
        """
        color_mode = ColorMode(color_mode)

        if color_mode == ColorMode.DIRECT:
            setattr(self, f'_{attribute}_color_mode', color_mode)
        elif color_mode in (ColorMode.CYCLE, ColorMode.COLORMAP):
            color_property = getattr(self, f'_{attribute}_color_property')
            if color_property == '':
                if self.properties:
                    new_color_property = next(iter(self.properties))
                    setattr(
                        self,
                        f'_{attribute}_color_property',
                        new_color_property,
                    )
                    warnings.warn(
                        f'_{attribute}_color_property was not set, '
                        f'setting to: {new_color_property}'
                    )
                else:
                    raise ValueError(
                        'There must be a valid Shapes.properties to use '
                        f'{color_mode}'
                    )

            # ColorMode.COLORMAP can only be applied to numeric properties
            color_property = getattr(self, f'_{attribute}_color_property')
            if (color_mode == ColorMode.COLORMAP) and not issubclass(
                self.properties[color_property].dtype.type, np.number
            ):
                raise TypeError(
                    'selected property must be numeric to use ColorMode.COLORMAP'
                )
            setattr(self, f'_{attribute}_color_mode', color_mode)
            self.refresh_colors()

    def _set_color_cycle(self, color_cycle: np.ndarray, attribute: str):
        """Set the face_color_cycle or edge_color_cycle property

        Parameters
        ----------
        color_cycle : (N, 4) or (N, 1) array
            The value for setting edge or face_color_cycle
        attribute : str in {'edge', 'face'}
            The name of the attribute to set the color of.
            Should be 'edge' for edge_color or 'face' for face_color.
        """
        transformed_color_cycle, transformed_colors = transform_color_cycle(
            color_cycle=color_cycle,
            elem_name=f'{attribute}_color_cycle',
            default="white",
        )
        setattr(self, f'_{attribute}_color_cycle_values', transformed_colors)
        setattr(self, f'_{attribute}_color_cycle', transformed_color_cycle)

        if self._update_properties is True:
            color_mode = getattr(self, f'_{attribute}_color_mode')
            if color_mode == ColorMode.CYCLE:
                self.refresh_colors(update_color_mapping=True)

    @property
    def edge_width(self):
        """list of float: edge width for each shape."""
        return self._data_view.edge_widths

    @property
    def z_index(self):
        """list of int: z_index for each shape."""
        return self._data_view.z_indices

    @property
    def selected_data(self):
        """set: set of currently selected shapes."""
        return self._selected_data

    @selected_data.setter
    def selected_data(self, selected_data):
        self._selected_data = set(selected_data)
        self._selected_box = self.interaction_box(self._selected_data)

        # Update properties based on selected shapes
        if len(selected_data) > 0:
            selected_data_indices = list(selected_data)
            selected_face_colors = self._data_view._face_color[
                selected_data_indices
            ]
            face_colors = np.unique(selected_face_colors, axis=0)
            if len(face_colors) == 1:
                face_color = face_colors[0]
                with self.block_update_properties():
                    self.current_face_color = face_color

            selected_edge_colors = self._data_view._edge_color[
                selected_data_indices
            ]
            edge_colors = np.unique(selected_edge_colors, axis=0)
            if len(edge_colors) == 1:
                edge_color = edge_colors[0]
                with self.block_update_properties():
                    self.current_edge_color = edge_color

            edge_width = list(
                {self._data_view.shapes[i].edge_width for i in selected_data}
            )
            if len(edge_width) == 1:
                edge_width = edge_width[0]
                with self.block_update_properties():
                    self.current_edge_width = edge_width
            properties = {
                k: np.unique(v[selected_data_indices], axis=0)
                for k, v in self.properties.items()
            }
            n_unique_properties = np.array(
                [len(v) for v in properties.values()]
            )
            if np.all(n_unique_properties == 1):
                with self.block_update_properties():
                    self.current_properties = properties

    def _set_color(self, color, attribute: str):
        """Set the face_color or edge_color property

        Parameters
        ----------
        color : (N, 4) array or str
            The value for setting edge or face_color
        attribute : str in {'edge', 'face'}
            The name of the attribute to set the color of.
            Should be 'edge' for edge_color or 'face' for face_color.
        """
        if self._is_color_mapped(color):
            if guess_continuous(self.properties[color]):
                setattr(self, f'_{attribute}_color_mode', ColorMode.COLORMAP)
            else:
                setattr(self, f'_{attribute}_color_mode', ColorMode.CYCLE)
            setattr(self, f'_{attribute}_color_property', color)
            self.refresh_colors()

        else:
            if len(self.data) > 0:
                transformed_color = transform_color_with_defaults(
                    num_entries=len(self.data),
                    colors=color,
                    elem_name="face_color",
                    default="white",
                )
                colors = normalize_and_broadcast_colors(
                    len(self.data), transformed_color
                )
            else:
                colors = np.empty((0, 4))

            setattr(self._data_view, f'{attribute}_color', colors)
            setattr(self, f'_{attribute}_color_mode', ColorMode.DIRECT)

            color_event = getattr(self.events, f'{attribute}_color')
            color_event()

    def refresh_colors(self, update_color_mapping: bool = False):
        """Calculate and update face and edge colors if using a cycle or color map

        Parameters
        ----------
        update_color_mapping : bool
            If set to True, the function will recalculate the color cycle map
            or colormap (whichever is being used). If set to False, the function
            will use the current color cycle map or color map. For example, if you
            are adding/modifying shapes and want them to be colored with the same
            mapping as the other shapes (i.e., the new shapes shouldn't affect
            the color cycle map or colormap), set update_color_mapping=False.
            Default value is False.
        """

        self._refresh_color('face', update_color_mapping)
        self._refresh_color('edge', update_color_mapping)

    def _refresh_color(
        self, attribute: str, update_color_mapping: bool = False
    ):
        """Calculate and update face or edge colors if using a cycle or color map

        Parameters
        ----------
        attribute : str  in {'edge', 'face'}
            The name of the attribute to set the color of.
            Should be 'edge' for edge_color or 'face' for face_color.
        update_color_mapping : bool
            If set to True, the function will recalculate the color cycle map
            or colormap (whichever is being used). If set to False, the function
            will use the current color cycle map or color map. For example, if you
            are adding/modifying shapes and want them to be colored with the same
            mapping as the other shapes (i.e., the new shapes shouldn't affect
            the color cycle map or colormap), set update_color_mapping=False.
            Default value is False.
        """
        if self._update_properties:
            color_mode = getattr(self, f'_{attribute}_color_mode')
            if color_mode in [ColorMode.CYCLE, ColorMode.COLORMAP]:
                colors = self._map_color(attribute, update_color_mapping)
                setattr(self._data_view, f'{attribute}_color', colors)

                color_event = getattr(self.events, f'{attribute}_color')
                color_event()

    def _initialize_color(self, color, attribute: str, n_shapes: int):
        """Get the face/edge colors the Shapes layer will be initialized with

        Parameters
        ----------
        color : (N, 4) array or str
            The value for setting edge or face_color
        attribute : str in {'edge', 'face'}
            The name of the attribute to set the color of.
            Should be 'edge' for edge_color or 'face' for face_color.

        Returns
        -------
        init_colors : (N, 4) array or str
            The calculated values for setting edge or face_color
        """
        if self._is_color_mapped(color):
            if guess_continuous(self.properties[color]):
                setattr(self, f'_{attribute}_color_mode', ColorMode.COLORMAP)
            else:
                setattr(self, f'_{attribute}_color_mode', ColorMode.CYCLE)
            setattr(self, f'_{attribute}_color_property', color)
            init_colors = self._map_color(
                attribute, update_color_mapping=False
            )

        else:
            if n_shapes > 0:
                transformed_color = transform_color_with_defaults(
                    num_entries=n_shapes,
                    colors=color,
                    elem_name="face_color",
                    default="white",
                )
                init_colors = normalize_and_broadcast_colors(
                    n_shapes, transformed_color
                )
            else:
                init_colors = np.empty((0, 4))

            setattr(self, f'_{attribute}_color_mode', ColorMode.DIRECT)

        return init_colors

    def _map_color(self, attribute: str, update_color_mapping: bool = False):
        """Calculate the mapping for face or edge colors if using a cycle or color map

        Parameters
        ----------
        attribute : str  in {'edge', 'face'}
            The name of the attribute to set the color of.
            Should be 'edge' for edge_color or 'face' for face_color.
        update_color_mapping : bool
            If set to True, the function will recalculate the color cycle map
            or colormap (whichever is being used). If set to False, the function
            will use the current color cycle map or color map. For example, if you
            are adding/modifying shapes and want them to be colored with the same
            mapping as the other shapes (i.e., the new shapes shouldn't affect
            the color cycle map or colormap), set update_color_mapping=False.
            Default value is False.

        Returns
        -------
        colors : (N, 4) array or str
            The calculated values for setting edge or face_color
        """
        color_mode = getattr(self, f'_{attribute}_color_mode')
        if color_mode == ColorMode.CYCLE:
            color_property = getattr(self, f'_{attribute}_color_property')
            color_properties = self.properties[color_property]
            if update_color_mapping:
                color_cycle = getattr(self, f'_{attribute}_color_cycle')
                color_cycle_map = {
                    k: np.squeeze(transform_color(c))
                    for k, c in zip(np.unique(color_properties), color_cycle)
                }
                setattr(self, f'{attribute}_color_cycle_map', color_cycle_map)

            else:
                # add properties if they are not in the colormap
                # and update_color_mapping==False
                color_cycle_map = getattr(self, f'{attribute}_color_cycle_map')
                color_cycle_keys = [*color_cycle_map]
                props_in_map = np.in1d(color_properties, color_cycle_keys)
                if not np.all(props_in_map):
                    props_to_add = np.unique(
                        color_properties[np.logical_not(props_in_map)]
                    )
                    color_cycle = getattr(self, f'_{attribute}_color_cycle')
                    for prop in props_to_add:
                        color_cycle_map[prop] = np.squeeze(
                            transform_color(next(color_cycle))
                        )
                    setattr(
                        self,
                        f'{attribute}_color_cycle_map',
                        color_cycle_map,
                    )
            colors = np.array([color_cycle_map[x] for x in color_properties])
            if len(colors) == 0:
                colors = np.empty((0, 4))

        elif color_mode == ColorMode.COLORMAP:
            color_property = getattr(self, f'_{attribute}_color_property')
            color_properties = self.properties[color_property]
            if len(color_properties) > 0:
                contrast_limits = getattr(self, f'{attribute}_contrast_limits')
                colormap = getattr(self, f'{attribute}_colormap')
                if update_color_mapping or contrast_limits is None:

                    colors, contrast_limits = map_property(
                        prop=color_properties, colormap=colormap
                    )
                    setattr(
                        self,
                        f'{attribute}_contrast_limits',
                        contrast_limits,
                    )
                else:

                    colors, _ = map_property(
                        prop=color_properties,
                        colormap=colormap,
                        contrast_limits=contrast_limits,
                    )
            else:
                colors = np.empty((0, 4))

        return colors

    def _get_new_shape_color(self, adding: int, attribute: str):
        """Get the color for the shape(s) to be added.

        Parameters
        ----------
        adding : int
            the number of shapes that were added
            (and thus the number of color entries to add)
        attribute : str in {'edge', 'face'}
            The name of the attribute to set the color of.
            Should be 'edge' for edge_color_mode or 'face' for face_color_mode.

        Returns
        -------
        new_colors : (N, 4) array
            (Nx4) RGBA array of colors for the N new shapes
        """
        color_mode = getattr(self, f'_{attribute}_color_mode')
        if color_mode == ColorMode.DIRECT:
            current_face_color = getattr(self, f'_current_{attribute}_color')
            new_colors = np.tile(current_face_color, (adding, 1))
        elif color_mode == ColorMode.CYCLE:
            property_name = getattr(self, f'_{attribute}_color_property')
            color_property_value = self.current_properties[property_name][0]

            # check if the new color property is in the cycle map
            # and add it if it is not
            color_cycle_map = getattr(self, f'{attribute}_color_cycle_map')
            color_cycle_keys = [*color_cycle_map]
            if color_property_value not in color_cycle_keys:
                color_cycle = getattr(self, f'_{attribute}_color_cycle')
                color_cycle_map[color_property_value] = np.squeeze(
                    transform_color(next(color_cycle))
                )

                setattr(self, f'{attribute}_color_cycle_map', color_cycle_map)

            new_colors = np.tile(
                color_cycle_map[color_property_value], (adding, 1)
            )
        elif color_mode == ColorMode.COLORMAP:
            property_name = getattr(self, f'_{attribute}_color_property')
            color_property_value = self.current_properties[property_name][0]
            colormap = getattr(self, f'{attribute}_colormap')
            contrast_limits = getattr(self, f'_{attribute}_contrast_limits')

            fc, _ = map_property(
                prop=color_property_value,
                colormap=colormap,
                contrast_limits=contrast_limits,
            )
            new_colors = np.tile(fc, (adding, 1))

        return new_colors

    def _is_color_mapped(self, color):
        """ determines if the new color argument is for directly setting or cycle/colormap"""
        if isinstance(color, str):
            if color in self.properties:
                return True
            else:
                return False
        elif isinstance(color, (list, np.ndarray)):
            return False
        else:
            raise ValueError(
                'face_color should be the name of a color, an array of colors, or the name of an property'
            )

    def _get_state(self):
        """Get dictionary of layer state.

        Returns
        -------
        state : dict
            Dictionary of layer state.
        """
        state = self._get_base_state()
        state.update(
            {
                'ndim': self.ndim,
                'properties': self.properties,
                'text': self.text._get_state(),
                'shape_type': self.shape_type,
                'opacity': self.opacity,
                'z_index': self.z_index,
                'edge_width': self.edge_width,
                'face_color': self.face_color,
                'face_color_cycle': self.face_color_cycle,
                'face_colormap': self.face_colormap.name,
                'face_contrast_limits': self.face_contrast_limits,
                'edge_color': self.edge_color,
                'edge_color_cycle': self.edge_color_cycle,
                'edge_colormap': self.edge_colormap.name,
                'edge_contrast_limits': self.edge_contrast_limits,
                'data': self.data,
            }
        )
        return state

    @property
    def _indices_view(self):
        return np.where(self._data_view._displayed)[0]

    @property
    def _view_text(self) -> np.ndarray:
        """Get the values of the text elements in view

        Returns
        -------
        text : (N x 1) np.ndarray
            Array of text strings for the N text elements in view
        """
        return self.text.view_text(self._indices_view)

    @property
    def _view_text_coords(self) -> np.ndarray:
        """Get the coordinates of the text elements in view

        Returns
        -------
        text_coords : (N x D) np.ndarray
            Array of coordindates for the N text elements in view
        """
        # get the coordinates of the vertices for the shapes in view
        in_view_shapes_coords = [
            self._data_view.data[i] for i in self._indices_view
        ]

        # get the coordinates for the dimensions being displayed
        sliced_in_view_coords = [
            position[:, self._dims_displayed]
            for position in in_view_shapes_coords
        ]

        return self.text.compute_text_coords(
            sliced_in_view_coords, self._ndisplay
        )

    @property
    def mode(self):
        """MODE: Interactive mode. The normal, default mode is PAN_ZOOM, which
        allows for normal interactivity with the canvas.

        The SELECT mode allows for entire shapes to be selected, moved and
        resized.

        The DIRECT mode allows for shapes to be selected and their individual
        vertices to be moved.

        The VERTEX_INSERT and VERTEX_REMOVE modes allow for individual
        vertices either to be added to or removed from shapes that are already
        selected. Note that shapes cannot be selected in this mode.

        The ADD_RECTANGLE, ADD_ELLIPSE, ADD_LINE, ADD_PATH, and ADD_POLYGON
        modes all allow for their corresponding shape type to be added.
        """
        return str(self._mode)

    @mode.setter
    def mode(self, mode):
        mode = Mode(mode)

        if not self.editable:
            mode = Mode.PAN_ZOOM

        if mode == self._mode:
            return
        old_mode = self._mode

        if old_mode in [Mode.SELECT, Mode.DIRECT]:
            self.mouse_drag_callbacks.remove(select)
            self.mouse_move_callbacks.remove(highlight)
        elif old_mode == Mode.VERTEX_INSERT:
            self.mouse_drag_callbacks.remove(vertex_insert)
            self.mouse_move_callbacks.remove(highlight)
        elif old_mode == Mode.VERTEX_REMOVE:
            self.mouse_drag_callbacks.remove(vertex_remove)
            self.mouse_move_callbacks.remove(highlight)
        elif old_mode == Mode.ADD_RECTANGLE:
            self.mouse_drag_callbacks.remove(add_rectangle)
        elif old_mode == Mode.ADD_ELLIPSE:
            self.mouse_drag_callbacks.remove(add_ellipse)
        elif old_mode == Mode.ADD_LINE:
            self.mouse_drag_callbacks.remove(add_line)
        elif old_mode in [Mode.ADD_PATH, Mode.ADD_POLYGON]:
            self.mouse_drag_callbacks.remove(add_path_polygon)
            self.mouse_move_callbacks.remove(add_path_polygon_creating)

        if mode == Mode.PAN_ZOOM:
            self.cursor = 'standard'
            self.interactive = True
            self.help = trans._(
                'enter a selection mode to edit shape properties'
            )
        elif mode in [Mode.SELECT, Mode.DIRECT]:
            self.cursor = 'pointing'
            self.interactive = False
            self.help = trans._(
                'hold <space> to pan/zoom, press <{BACKSPACE}> to remove selected',
                BACKSPACE=BACKSPACE,
            )
            self.mouse_drag_callbacks.append(select)
            self.mouse_move_callbacks.append(highlight)
        elif mode in [Mode.VERTEX_INSERT, Mode.VERTEX_REMOVE]:
            self.cursor = 'cross'
            self.interactive = False
            self.help = trans._('hold <space> to pan/zoom')
            if mode == Mode.VERTEX_INSERT:
                self.mouse_drag_callbacks.append(vertex_insert)
            else:
                self.mouse_drag_callbacks.append(vertex_remove)
            self.mouse_move_callbacks.append(highlight)
        elif mode in [Mode.ADD_RECTANGLE, Mode.ADD_ELLIPSE, Mode.ADD_LINE]:
            self.cursor = 'cross'
            self.interactive = False
            self.help = trans._('hold <space> to pan/zoom')
            if mode == Mode.ADD_RECTANGLE:
                self.mouse_drag_callbacks.append(add_rectangle)
            elif mode == Mode.ADD_ELLIPSE:
                self.mouse_drag_callbacks.append(add_ellipse)
            elif mode == Mode.ADD_LINE:
                self.mouse_drag_callbacks.append(add_line)
        elif mode in [Mode.ADD_PATH, Mode.ADD_POLYGON]:
            self.cursor = 'cross'
            self.interactive = False
            self.help = trans._(
                'hold <space> to pan/zoom, ' 'press <esc> to finish drawing'
            )
            self.mouse_drag_callbacks.append(add_path_polygon)
            self.mouse_move_callbacks.append(add_path_polygon_creating)
        else:
            raise ValueError(trans._("Mode not recognized"))

        self._mode = mode

        draw_modes = [
            Mode.SELECT,
            Mode.DIRECT,
            Mode.VERTEX_INSERT,
            Mode.VERTEX_REMOVE,
        ]

        self.events.mode(mode=mode)

        # don't update thumbnail on mode changes
        with self.block_thumbnail_update():
            if not (mode in draw_modes and old_mode in draw_modes):
                # Shapes._finish_drawing() calls Shapes.refresh()
                self._finish_drawing()
            else:
                self.refresh()

    def _set_editable(self, editable=None):
        """Set editable mode based on layer properties."""
        if editable is None:
            if self._ndisplay == 3:
                self.editable = False
            else:
                self.editable = True

        if not self.editable:
            self.mode = Mode.PAN_ZOOM

    def add(
        self,
        data,
        *,
        shape_type='rectangle',
        edge_width=None,
        edge_color=None,
        face_color=None,
        z_index=None,
    ):
        """Add shapes to the current layer.

        Parameters
        ----------
        data : Array | Tuple(Array,str) | List[Array | Tuple(Array, str)] | Tuple(List[Array], str)
            List of shape data, where each element is either an (N, D) array of the
            N vertices of a shape in D dimensions or a tuple containing an array of
            the N vertices and the shape_type string. When a shape_type is present,
            it overrides keyword arg shape_type. Can be an 3-dimensional array
            if each shape has the same number of vertices.
        shape_type : string | list
            String of shape shape_type, must be one of "{'line', 'rectangle',
            'ellipse', 'path', 'polygon'}". If a list is supplied it must be
            the same length as the length of `data` and each element will be
            applied to each shape otherwise the same value will be used for all
            shapes. Overriden by data shape_type, if present.
        edge_width : float | list
            thickness of lines and edges. If a list is supplied it must be the
            same length as the length of `data` and each element will be
            applied to each shape otherwise the same value will be used for all
            shapes.
        edge_color : str | tuple | list
            If string can be any color name recognized by vispy or hex value if
            starting with `#`. If array-like must be 1-dimensional array with 3
            or 4 elements. If a list is supplied it must be the same length as
            the length of `data` and each element will be applied to each shape
            otherwise the same value will be used for all shapes.
        face_color : str | tuple | list
            If string can be any color name recognized by vispy or hex value if
            starting with `#`. If array-like must be 1-dimensional array with 3
            or 4 elements. If a list is supplied it must be the same length as
            the length of `data` and each element will be applied to each shape
            otherwise the same value will be used for all shapes.
        z_index : int | list
            Specifier of z order priority. Shapes with higher z order are
            displayed ontop of others. If a list is supplied it must be the
            same length as the length of `data` and each element will be
            applied to each shape otherwise the same value will be used for all
            shapes.
        """
        data, shape_type = extract_shape_type(data, shape_type)

        if edge_width is None:
            edge_width = self.current_edge_width

        n_new_shapes = number_of_shapes(data)

        if edge_color is None:
            edge_color = self._get_new_shape_color(
                n_new_shapes, attribute='edge'
            )
        if face_color is None:
            face_color = self._get_new_shape_color(
                n_new_shapes, attribute='face'
            )
        if self._data_view is not None:
            z_index = z_index or max(self._data_view._z_index, default=-1) + 1
        else:
            z_index = z_index or 0

        if n_new_shapes > 0:
            if len(self.properties) > 0:
                first_prop_key = next(iter(self.properties))
                n_prop_values = len(self.properties[first_prop_key])
            else:
                n_prop_values = 0
            total_shapes = n_new_shapes + self.nshapes
            if total_shapes > n_prop_values:
                n_props_to_add = total_shapes - n_prop_values
                for k in self.properties:
                    new_property = np.repeat(
                        self.current_properties[k], n_props_to_add, axis=0
                    )
                    self.properties[k] = np.concatenate(
                        (self.properties[k], new_property), axis=0
                    )
                self.text.add(self.current_properties, n_props_to_add)
            if total_shapes < n_prop_values:
                for k in self.properties:
                    self.properties[k] = self.properties[k][:total_shapes]
                n_props_to_remove = n_prop_values - total_shapes
                indices_to_remove = np.arange(n_prop_values)[
                    -n_props_to_remove:
                ]
                self.text.remove(indices_to_remove)

            self._add_shapes(
                data,
                shape_type=shape_type,
                edge_width=edge_width,
                edge_color=edge_color,
                face_color=face_color,
                z_index=z_index,
            )

    def _init_shapes(
        self,
        data,
        *,
        shape_type='rectangle',
        edge_width=None,
        edge_color=None,
        edge_color_cycle,
        edge_colormap,
        edge_contrast_limits,
        face_color=None,
        face_color_cycle,
        face_colormap,
        face_contrast_limits,
        z_index=None,
    ):
        """Add shapes to the data view.

        Parameters
        ----------
        data : Array | Tuple(Array,str) | List[Array | Tuple(Array, str)] | Tuple(List[Array], str)
            List of shape data, where each element is either an (N, D) array of the
            N vertices of a shape in D dimensions or a tuple containing an array of
            the N vertices and the shape_type string. When a shape_type is present,
            it overrides keyword arg shape_type. Can be an 3-dimensional array
            if each shape has the same number of vertices.
        shape_type : string | list
            String of shape shape_type, must be one of "{'line', 'rectangle',
            'ellipse', 'path', 'polygon'}". If a list is supplied it must be
            the same length as the length of `data` and each element will be
            applied to each shape otherwise the same value will be used for all
            shapes. Overriden by data shape_type, if present.
        edge_width : float | list
            thickness of lines and edges. If a list is supplied it must be the
            same length as the length of `data` and each element will be
            applied to each shape otherwise the same value will be used for all
            shapes.
        edge_color : str | tuple | list
            If string can be any color name recognized by vispy or hex value if
            starting with `#`. If array-like must be 1-dimensional array with 3
            or 4 elements. If a list is supplied it must be the same length as
            the length of `data` and each element will be applied to each shape
            otherwise the same value will be used for all shapes.
        face_color : str | tuple | list
            If string can be any color name recognized by vispy or hex value if
            starting with `#`. If array-like must be 1-dimensional array with 3
            or 4 elements. If a list is supplied it must be the same length as
            the length of `data` and each element will be applied to each shape
            otherwise the same value will be used for all shapes.
        z_index : int | list
            Specifier of z order priority. Shapes with higher z order are
            displayed ontop of others. If a list is supplied it must be the
            same length as the length of `data` and each element will be
            applied to each shape otherwise the same value will be used for all
            shapes.
        """

        n_shapes = number_of_shapes(data)
        with self.block_update_properties():
            self._edge_color_property = ''
            self.edge_color_cycle_map = {}
            self.edge_colormap = edge_colormap
            self._edge_contrast_limits = edge_contrast_limits
            if edge_color_cycle is None:
                edge_color_cycle = deepcopy(DEFAULT_COLOR_CYCLE)
            self.edge_color_cycle = edge_color_cycle
            edge_color = self._initialize_color(
                edge_color, attribute='edge', n_shapes=n_shapes
            )

            self._face_color_property = ''
            self.face_color_cycle_map = {}
            self.face_colormap = face_colormap
            self._face_contrast_limits = face_contrast_limits
            if face_color_cycle is None:
                face_color_cycle = deepcopy(DEFAULT_COLOR_CYCLE)
            self.face_color_cycle = face_color_cycle
            face_color = self._initialize_color(
                face_color, attribute='face', n_shapes=n_shapes
            )

        with self.block_thumbnail_update():
            self._add_shapes(
                data,
                shape_type=shape_type,
                edge_width=edge_width,
                edge_color=edge_color,
                face_color=face_color,
                z_index=z_index,
                z_refresh=False,
            )
            self._data_view._update_z_order()
            self.refresh_colors()

    def _add_shapes(
        self,
        data,
        *,
        shape_type='rectangle',
        edge_width=None,
        edge_color=None,
        face_color=None,
        z_index=None,
        z_refresh=True,
    ):
        """Add shapes to the data view.

        Parameters
        ----------
        data : Array | Tuple(Array,str) | List[Array | Tuple(Array, str)] | Tuple(List[Array], str)
            List of shape data, where each element is either an (N, D) array of the
            N vertices of a shape in D dimensions or a tuple containing an array of
            the N vertices and the shape_type string. When a shape_type is present,
            it overrides keyword arg shape_type. Can be an 3-dimensional array
            if each shape has the same number of vertices.
        shape_type : string | list
            String of shape shape_type, must be one of "{'line', 'rectangle',
            'ellipse', 'path', 'polygon'}". If a list is supplied it must be
            the same length as the length of `data` and each element will be
            applied to each shape otherwise the same value will be used for all
            shapes. Overriden by data shape_type, if present.
        edge_width : float | list
            thickness of lines and edges. If a list is supplied it must be the
            same length as the length of `data` and each element will be
            applied to each shape otherwise the same value will be used for all
            shapes.
        edge_color : str | tuple | list
            If string can be any color name recognized by vispy or hex value if
            starting with `#`. If array-like must be 1-dimensional array with 3
            or 4 elements. If a list is supplied it must be the same length as
            the length of `data` and each element will be applied to each shape
            otherwise the same value will be used for all shapes.
        face_color : str | tuple | list
            If string can be any color name recognized by vispy or hex value if
            starting with `#`. If array-like must be 1-dimensional array with 3
            or 4 elements. If a list is supplied it must be the same length as
            the length of `data` and each element will be applied to each shape
            otherwise the same value will be used for all shapes.
        z_index : int | list
            Specifier of z order priority. Shapes with higher z order are
            displayed ontop of others. If a list is supplied it must be the
            same length as the length of `data` and each element will be
            applied to each shape otherwise the same value will be used for all
            shapes.
        z_refresh : bool
            If set to true, the mesh elements are reindexed with the new z order.
            When shape_index is provided, z_refresh will be overwritten to false,
            as the z indices will not change.
            When adding a batch of shapes, set to false  and then call
            ShapesList._update_z_order() once at the end.
        """
        if edge_width is None:
            edge_width = self.current_edge_width
        if edge_color is None:
            edge_color = self._current_edge_color
        if face_color is None:
            face_color = self._current_face_color
        if self._data_view is not None:
            z_index = z_index or max(self._data_view._z_index, default=-1) + 1
        else:
            z_index = z_index or 0

        if len(data) > 0:
            if np.array(data[0]).ndim == 1:
                # If a single array for a shape has been passed turn into list
                data = [data]

            # transform the colors
            transformed_ec = transform_color_with_defaults(
                num_entries=len(data),
                colors=edge_color,
                elem_name="edge_color",
                default="white",
            )
            transformed_edge_color = normalize_and_broadcast_colors(
                len(data), transformed_ec
            )
            transformed_fc = transform_color_with_defaults(
                num_entries=len(data),
                colors=face_color,
                elem_name="face_color",
                default="white",
            )
            transformed_face_color = normalize_and_broadcast_colors(
                len(data), transformed_fc
            )

            # Turn input arguments into iterables
            shape_inputs = zip(
                data,
                ensure_iterable(shape_type),
                ensure_iterable(edge_width),
                transformed_edge_color,
                transformed_face_color,
                ensure_iterable(z_index),
            )

            self._add_shapes_to_view(shape_inputs, self._data_view)

        self._display_order_stored = copy(self._dims_order)
        self._ndisplay_stored = copy(self._ndisplay)
        self._update_dims()

    def _add_shapes_to_view(self, shape_inputs, data_view):
        """Build new shapes and add them to the _data_view"""
        for d, st, ew, ec, fc, z in shape_inputs:

            shape_cls = shape_classes[ShapeType(st)]
            shape = shape_cls(
                d,
                edge_width=ew,
                z_index=z,
                dims_order=self._dims_order,
                ndisplay=self._ndisplay,
            )

            # Add shape
            data_view.add(shape, edge_color=ec, face_color=fc, z_refresh=False)
        data_view._update_z_order()

    def _validate_properties(
        self, properties: Dict[str, np.ndarray], n_shapes: Optional[int] = None
    ) -> Dict[str, np.ndarray]:
        """Validates the type and size of the properties"""
        if n_shapes is None:
            n_shapes = len(self.data)
        for k, v in properties.items():
            if len(v) != n_shapes:
                raise ValueError(
                    'the number of properties must equal the number of shapes'
                )
            # ensure the property values are a numpy array
            if type(v) != np.ndarray:
                properties[k] = np.asarray(v)

        return properties

    @property
    def text(self) -> TextManager:
        """TextManager: The TextManager object containing the text properties"""
        return self._text

    @text.setter
    def text(self, text):
        self._text._set_text(
            text, n_text=len(self.data), properties=self.properties
        )

    def refresh_text(self):
        """Refresh the text values.

        This is generally used if the properties were updated without changing the data
        """
        self.text.refresh_text(self.properties)

    def _set_view_slice(self):
        """Set the view given the slicing indices."""
        if not self._ndisplay == self._ndisplay_stored:
            self.selected_data = set()
            self._data_view.ndisplay = min(self.ndim, self._ndisplay)
            self._ndisplay_stored = copy(self._ndisplay)
            self._clipboard = {}

        if not self._dims_order == self._display_order_stored:
            self.selected_data = set()
            self._data_view.update_dims_order(self._dims_order)
            self._display_order_stored = copy(self._dims_order)
            # Clear clipboard if dimensions swap
            self._clipboard = {}

        slice_key = np.array(self._slice_indices)[
            list(self._dims_not_displayed)
        ]
        if not np.all(slice_key == self._data_view.slice_key):
            self.selected_data = set()
        self._data_view.slice_key = slice_key

    def interaction_box(self, index):
        """Create the interaction box around a shape or list of shapes.
        If a single index is passed then the boudning box will be inherited
        from that shapes interaction box. If list of indices is passed it will
        be computed directly.

        Parameters
        ----------
        index : int | list
            Index of a single shape, or a list of shapes around which to
            construct the interaction box

        Returns
        -------
        box : np.ndarray
            10x2 array of vertices of the interaction box. The first 8 points
            are the corners and midpoints of the box in clockwise order
            starting in the upper-left corner. The 9th point is the center of
            the box, and the last point is the location of the rotation handle
            that can be used to rotate the box
        """
        if isinstance(index, (list, np.ndarray, set)):
            if len(index) == 0:
                box = None
            elif len(index) == 1:
                box = copy(self._data_view.shapes[list(index)[0]]._box)
            else:
                indices = np.isin(self._data_view.displayed_index, list(index))
                box = create_box(self._data_view.displayed_vertices[indices])
        else:
            box = copy(self._data_view.shapes[index]._box)

        if box is not None:
            rot = box[Box.TOP_CENTER]
            length_box = np.linalg.norm(
                box[Box.BOTTOM_LEFT] - box[Box.TOP_LEFT]
            )
            if length_box > 0:
                r = self._rotation_handle_length * self.scale_factor
                rot = (
                    rot
                    - r
                    * (box[Box.BOTTOM_LEFT] - box[Box.TOP_LEFT])
                    / length_box
                )
            box = np.append(box, [rot], axis=0)

        return box

    def _outline_shapes(self):
        """Find outlines of any selected or hovered shapes.

        Returns
        -------
        vertices : None | np.ndarray
            Nx2 array of any vertices of outline or None
        triangles : None | np.ndarray
            Mx3 array of any indices of vertices for triangles of outline or
            None
        """
        if self._value is not None and (
            self._value[0] is not None or len(self.selected_data) > 0
        ):
            if len(self.selected_data) > 0:
                index = list(self.selected_data)
                if self._value[0] is not None:
                    if self._value[0] in index:
                        pass
                    else:
                        index.append(self._value[0])
                index.sort()
            else:
                index = self._value[0]

            centers, offsets, triangles = self._data_view.outline(index)
            vertices = centers + (
                self.scale_factor * self._highlight_width * offsets
            )
            vertices = vertices[:, ::-1]
        else:
            vertices = None
            triangles = None

        return vertices, triangles

    def _compute_vertices_and_box(self):
        """Compute location of highlight vertices and box for rendering.

        Returns
        -------
        vertices : np.ndarray
            Nx2 array of any vertices to be rendered as Markers
        face_color : str
            String of the face color of the Markers
        edge_color : str
            String of the edge color of the Markers and Line for the box
        pos : np.ndarray
            Nx2 array of vertices of the box that will be rendered using a
            Vispy Line
        width : float
            Width of the box edge
        """
        if len(self.selected_data) > 0:
            if self._mode == Mode.SELECT:
                # If in select mode just show the interaction boudning box
                # including its vertices and the rotation handle
                box = self._selected_box[Box.WITH_HANDLE]
                if self._value[0] is None:
                    face_color = 'white'
                elif self._value[1] is None:
                    face_color = 'white'
                else:
                    face_color = self._highlight_color
                edge_color = self._highlight_color
                vertices = box[:, ::-1]
                # Use a subset of the vertices of the interaction_box to plot
                # the line around the edge
                pos = box[Box.LINE_HANDLE][:, ::-1]
                width = 1.5
            elif self._mode in (
                [
                    Mode.DIRECT,
                    Mode.ADD_PATH,
                    Mode.ADD_POLYGON,
                    Mode.ADD_RECTANGLE,
                    Mode.ADD_ELLIPSE,
                    Mode.ADD_LINE,
                    Mode.VERTEX_INSERT,
                    Mode.VERTEX_REMOVE,
                ]
            ):
                # If in one of these mode show the vertices of the shape itself
                inds = np.isin(
                    self._data_view.displayed_index, list(self.selected_data)
                )
                vertices = self._data_view.displayed_vertices[inds][:, ::-1]
                # If currently adding path don't show box over last vertex
                if self._mode == Mode.ADD_PATH:
                    vertices = vertices[:-1]

                if self._value[0] is None:
                    face_color = 'white'
                elif self._value[1] is None:
                    face_color = 'white'
                else:
                    face_color = self._highlight_color
                edge_color = self._highlight_color
                pos = None
                width = 0
            else:
                # Otherwise show nothing
                vertices = np.empty((0, 2))
                face_color = 'white'
                edge_color = 'white'
                pos = None
                width = 0
        elif self._is_selecting:
            # If currently dragging a selection box just show an outline of
            # that box
            vertices = np.empty((0, 2))
            edge_color = self._highlight_color
            face_color = 'white'
            box = create_box(self._drag_box)
            width = 1.5
            # Use a subset of the vertices of the interaction_box to plot
            # the line around the edge
            pos = box[Box.LINE][:, ::-1]
        else:
            # Otherwise show nothing
            vertices = np.empty((0, 2))
            face_color = 'white'
            edge_color = 'white'
            pos = None
            width = 0

        return vertices, face_color, edge_color, pos, width

    def _set_highlight(self, force=False):
        """Render highlights of shapes.

        Includes boundaries, vertices, interaction boxes, and the drag
        selection box when appropriate.

        Parameters
        ----------
        force : bool
            Bool that forces a redraw to occur when `True`
        """
        # Check if any shape or vertex ids have changed since last call
        if (
            self.selected_data == self._selected_data_stored
            and np.all(self._value == self._value_stored)
            and np.all(self._drag_box == self._drag_box_stored)
        ) and not force:
            return
        self._selected_data_stored = copy(self.selected_data)
        self._value_stored = copy(self._value)
        self._drag_box_stored = copy(self._drag_box)
        self.events.highlight()

    def _finish_drawing(self, event=None):
        """Reset properties used in shape drawing."""
        index = copy(self._moving_value[0])
        self._is_moving = False
        self.selected_data = set()
        self._drag_start = None
        self._drag_box = None
        self._is_selecting = False
        self._fixed_vertex = None
        self._value = (None, None)
        self._moving_value = (None, None)
        if self._is_creating is True and self._mode == Mode.ADD_PATH:
            vertices = self._data_view.shapes[index].data
            if len(vertices) <= 2:
                self._data_view.remove(index)
            else:
                self._data_view.edit(index, vertices[:-1])
        if self._is_creating is True and self._mode == Mode.ADD_POLYGON:
            vertices = self._data_view.shapes[index].data
            if len(vertices) <= 3:
                self._data_view.remove(index)
            else:
                self._data_view.edit(index, vertices[:-1])
        self._is_creating = False
        self._update_dims()

    @contextmanager
    def block_thumbnail_update(self):
        """Use this context manager to block thumbnail updates"""
        self._allow_thumbnail_update = False
        yield
        self._allow_thumbnail_update = True

    def _update_thumbnail(self, event=None):
        """Update thumbnail with current shapes and colors."""

        # don't update the thumbnail if dragging a shape
        if self._is_moving is False and self._allow_thumbnail_update is True:
            # calculate min vals for the vertices and pad with 0.5
            # the offset is needed to ensure that the top left corner of the shapes
            # corresponds to the top left corner of the thumbnail
            de = self._extent_data
            offset = np.array([de[0, d] for d in self._dims_displayed]) + 0.5
            # calculate range of values for the vertices and pad with 1
            # padding ensures the entire shape can be represented in the thumbnail
            # without getting clipped
            shape = np.ceil(
                [de[1, d] - de[0, d] + 1 for d in self._dims_displayed]
            ).astype(int)
            zoom_factor = np.divide(
                self._thumbnail_shape[:2], shape[-2:]
            ).min()

            colormapped = self._data_view.to_colors(
                colors_shape=self._thumbnail_shape[:2],
                zoom_factor=zoom_factor,
                offset=offset[-2:],
                max_shapes=self._max_shapes_thumbnail,
            )

            self.thumbnail = colormapped

    def remove_selected(self):
        """Remove any selected shapes."""
        index = list(self.selected_data)
        to_remove = sorted(index, reverse=True)
        for ind in to_remove:
            self._data_view.remove(ind)

        if len(index) > 0:
            for k in self.properties:
                self.properties[k] = np.delete(
                    self.properties[k], index, axis=0
                )
            self.text.remove(index)
            self._data_view._edge_color = np.delete(
                self._data_view._edge_color, index, axis=0
            )
            self._data_view._face_color = np.delete(
                self._data_view._face_color, index, axis=0
            )
        self.selected_data = set()
        self._finish_drawing()

    def _rotate_box(self, angle, center=[0, 0]):
        """Perform a rotation on the selected box.

        Parameters
        ----------
        angle : float
            angle specifying rotation of shapes in degrees.
        center : list
            coordinates of center of rotation.
        """
        theta = np.radians(angle)
        transform = np.array(
            [[np.cos(theta), np.sin(theta)], [-np.sin(theta), np.cos(theta)]]
        )
        box = self._selected_box - center
        self._selected_box = box @ transform.T + center

    def _scale_box(self, scale, center=[0, 0]):
        """Perform a scaling on the selected box.

        Parameters
        ----------
        scale : float, list
            scalar or list specifying rescaling of shape.
        center : list
            coordinates of center of rotation.
        """
        if not isinstance(scale, (list, np.ndarray)):
            scale = [scale, scale]
        box = self._selected_box - center
        box = np.array(box * scale)
        if not np.all(box[Box.TOP_CENTER] == box[Box.HANDLE]):
            r = self._rotation_handle_length * self.scale_factor
            handle_vec = box[Box.HANDLE] - box[Box.TOP_CENTER]
            cur_len = np.linalg.norm(handle_vec)
            box[Box.HANDLE] = box[Box.TOP_CENTER] + r * handle_vec / cur_len
        self._selected_box = box + center

    def _transform_box(self, transform, center=[0, 0]):
        """Perform a linear transformation on the selected box.

        Parameters
        ----------
        transform : np.ndarray
            2x2 array specifying linear transform.
        center : list
            coordinates of center of rotation.
        """
        box = self._selected_box - center
        box = box @ transform.T
        if not np.all(box[Box.TOP_CENTER] == box[Box.HANDLE]):
            r = self._rotation_handle_length * self.scale_factor
            handle_vec = box[Box.HANDLE] - box[Box.TOP_CENTER]
            cur_len = np.linalg.norm(handle_vec)
            box[Box.HANDLE] = box[Box.TOP_CENTER] + r * handle_vec / cur_len
        self._selected_box = box + center

    def expand_shape(self, data):
        """Expand shape from 2D to the full data dims.

        expand_shape is deprecated and will be removed in version 0.4.9.
        It should no longer be used as layers should will soon not know
        which dimensions are displayed. Instead you should work with
        full nD shape data as much as possible.

        Parameters
        ----------
        data : array
            2D data array of shape to be expanded.

        Returns
        -------
        data_full : array
            Full D dimensional data array of the shape.
        """
        warnings.warn(
            "expand_shape is deprecated and will be removed in version 0.4.9."
            " It should no longer be used as layers should will soon not know"
            " which dimensions are displayed. Instead you should work with"
            " full nD shape data as much as possible.",
            category=DeprecationWarning,
            stacklevel=2,
        )

        if self.ndim == 2:
            data_full = data[:, self._dims_displayed_order]
        else:
            data_full = np.zeros((len(data), self.ndim), dtype=float)
            indices = np.array(self._slice_indices)
            data_full[:, self._dims_not_displayed] = indices[
                self._dims_not_displayed
            ]
            data_full[:, self._dims_displayed] = data

        return data_full

    def _get_value(self, position):
        """Value of the data at a position in data coordinates.

        Parameters
        ----------
        position : tuple
            Position in data coordinates.

        Returns
        -------
        shape : int | None
            Index of shape if any that is at the coordinates. Returns `None`
            if no shape is found.
        vertex : int | None
            Index of vertex if any that is at the coordinates. Returns `None`
            if no vertex is found.
        """
        if self._ndisplay == 3:
            return (None, None)

        if self._is_moving:
            return self._moving_value

        coord = [position[i] for i in self._dims_displayed]

        # Check selected shapes
        value = None
        selected_index = list(self.selected_data)
        if len(selected_index) > 0:
            if self._mode == Mode.SELECT:
                # Check if inside vertex of interaction box or rotation handle
                box = self._selected_box[Box.WITH_HANDLE]
                distances = abs(box - coord)

                # Get the vertex sizes
                sizes = self._vertex_size * self.scale_factor / 2

                # Check if any matching vertices
                matches = np.all(distances <= sizes, axis=1).nonzero()
                if len(matches[0]) > 0:
                    value = (selected_index[0], matches[0][-1])
            elif self._mode in (
                [Mode.DIRECT, Mode.VERTEX_INSERT, Mode.VERTEX_REMOVE]
            ):
                # Check if inside vertex of shape
                inds = np.isin(self._data_view.displayed_index, selected_index)
                vertices = self._data_view.displayed_vertices[inds]
                distances = abs(vertices - coord)

                # Get the vertex sizes
                sizes = self._vertex_size * self.scale_factor / 2

                # Check if any matching vertices
                matches = np.all(distances <= sizes, axis=1).nonzero()[0]
                if len(matches) > 0:
                    index = inds.nonzero()[0][matches[-1]]
                    shape = self._data_view.displayed_index[index]
                    vals, idx = np.unique(
                        self._data_view.displayed_index, return_index=True
                    )
                    shape_in_list = list(vals).index(shape)
                    value = (shape, index - idx[shape_in_list])

        if value is None:
            # Check if mouse inside shape
            shape = self._data_view.inside(coord)
            value = (shape, None)

        return value

    def move_to_front(self):
        """Moves selected objects to be displayed in front of all others."""
        if len(self.selected_data) == 0:
            return
        new_z_index = max(self._data_view._z_index) + 1
        for index in self.selected_data:
            self._data_view.update_z_index(index, new_z_index)
        self.refresh()

    def move_to_back(self):
        """Moves selected objects to be displayed behind all others."""
        if len(self.selected_data) == 0:
            return
        new_z_index = min(self._data_view._z_index) - 1
        for index in self.selected_data:
            self._data_view.update_z_index(index, new_z_index)
        self.refresh()

    def _copy_data(self):
        """Copy selected shapes to clipboard."""
        if len(self.selected_data) > 0:
            index = list(self.selected_data)
            self._clipboard = {
                'data': [
                    deepcopy(self._data_view.shapes[i])
                    for i in self._selected_data
                ],
                'edge_color': deepcopy(self._data_view._edge_color[index]),
                'face_color': deepcopy(self._data_view._face_color[index]),
                'properties': {
                    k: deepcopy(v[index]) for k, v in self.properties.items()
                },
                'indices': self._slice_indices,
            }
            if len(self.text.values) == 0:
                self._clipboard['text'] = np.empty(0)
            else:
                self._clipboard['text'] = deepcopy(self.text.values[index])
        else:
            self._clipboard = {}

    def _paste_data(self):
        """Paste any shapes from clipboard and then selects them."""
        cur_shapes = self.nshapes
        if len(self._clipboard.keys()) > 0:
            # Calculate offset based on dimension shifts
            offset = [
                self._slice_indices[i] - self._clipboard['indices'][i]
                for i in self._dims_not_displayed
            ]

            for k in self.properties:
                self.properties[k] = np.concatenate(
                    (self.properties[k], self._clipboard['properties'][k]),
                    axis=0,
                )

            # Add new shape data
            for i, s in enumerate(self._clipboard['data']):
                shape = deepcopy(s)
                data = copy(shape.data)
                data[:, self._dims_not_displayed] = data[
                    :, self._dims_not_displayed
                ] + np.array(offset)
                shape.data = data
                face_color = self._clipboard['face_color'][i]
                edge_color = self._clipboard['edge_color'][i]
                self._data_view.add(
                    shape, face_color=face_color, edge_color=edge_color
                )

            if len(self._clipboard['text']) > 0:
                self.text._values = np.concatenate(
                    (self.text.values, self._clipboard['text']), axis=0
                )

            self.selected_data = set(
                range(cur_shapes, cur_shapes + len(self._clipboard['data']))
            )

            self.move_to_front()

    def to_masks(self, mask_shape=None):
        """Return an array of binary masks, one for each shape.

        Parameters
        ----------
        mask_shape : np.ndarray | tuple | None
            tuple defining shape of mask to be generated. If non specified,
            takes the max of all the vertiecs

        Returns
        -------
        masks : np.ndarray
            Array where there is one binary mask for each shape
        """
        if mask_shape is None:
            mask_shape = self._extent_data[1] - self._extent_data[0]

        mask_shape = np.ceil(mask_shape).astype('int')
        masks = self._data_view.to_masks(mask_shape=mask_shape)

        return masks

    def to_labels(self, labels_shape=None):
        """Return an integer labels image.

        Parameters
        ----------
        labels_shape : np.ndarray | tuple | None
            Tuple defining shape of labels image to be generated. If non
            specified, takes the max of all the vertiecs

        Returns
        -------
        labels : np.ndarray
            Integer array where each value is either 0 for background or an
            integer up to N for points inside the shape at the index value - 1.
            For overlapping shapes z-ordering will be respected.
        """
        if labels_shape is None:
            labels_shape = self._extent_data[1] - self._extent_data[0]

        labels_shape = np.ceil(labels_shape).astype('int')
        labels = self._data_view.to_labels(labels_shape=labels_shape)

        return labels
