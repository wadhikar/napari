import gc
import sys
from unittest import mock

import pytest

import napari
from napari import __main__


@pytest.fixture
def mock_run():
    """mock to prevent starting the event loop."""
    with mock.patch('napari._qt.widgets.qt_splash_screen.NapariSplashScreen'):
        with mock.patch('napari.__main__.run'):
            yield napari.__main__.run


def test_cli_works(monkeypatch, capsys):
    """Test the cli runs and shows help"""
    monkeypatch.setattr(sys, 'argv', ['napari', '-h'])
    with pytest.raises(SystemExit):
        __main__._run()
    assert 'napari command line viewer.' in str(capsys.readouterr())


def test_cli_shows_plugins(monkeypatch, capsys):
    """Test the cli --info runs and shows plugins"""
    monkeypatch.setattr(napari.plugins, 'dock_widgets', dict())
    monkeypatch.setattr(napari.plugins, 'function_widgets', dict())
    monkeypatch.setattr(sys, 'argv', ['napari', '--info'])
    with pytest.raises(SystemExit):
        __main__._run()
    assert 'svg' in str(capsys.readouterr())


def test_cli_parses_unknowns(mock_run, monkeypatch):
    """test that we can parse layer keyword arg variants"""

    def assert_kwargs(*args, **kwargs):
        assert args == (["file"],)
        assert kwargs['contrast_limits'] == (0, 1)

    # testing all the variants of literal_evals
    monkeypatch.setattr(napari.__main__, 'view_path', assert_kwargs)
    with monkeypatch.context() as m:
        m.setattr(sys, 'argv', ['n', 'file', '--contrast-limits', '(0, 1)'])
        __main__._run()
    with monkeypatch.context() as m:
        m.setattr(sys, 'argv', ['n', 'file', '--contrast-limits', '(0,1)'])
        __main__._run()
    with monkeypatch.context() as m:
        m.setattr(sys, 'argv', ['n', 'file', '--contrast-limits=(0, 1)'])
        __main__._run()
    with monkeypatch.context() as m:
        m.setattr(sys, 'argv', ['n', 'file', '--contrast-limits=(0,1)'])
        __main__._run()


def test_cli_raises(monkeypatch):
    """test that unknown kwargs raise the correct errors."""
    with monkeypatch.context() as m:
        m.setattr(sys, 'argv', ['napari', 'path/to/file', '--nonsense'])
        with pytest.raises(SystemExit) as e:
            __main__._run()
        assert str(e.value) == 'error: unrecognized arguments: --nonsense'

    with monkeypatch.context() as m:
        m.setattr(sys, 'argv', ['napari', 'path/to/file', '--gamma'])
        with pytest.raises(SystemExit) as e:
            __main__._run()
        assert str(e.value) == 'error: argument --gamma expected one argument'


@mock.patch('runpy.run_path')
def test_cli_runscript(run_path, monkeypatch, tmp_path):
    """Test that running napari script.py runs a script"""
    script = tmp_path / 'test.py'
    script.write_text('import napari; v = napari.Viewer(show=False)')

    with monkeypatch.context() as m:
        m.setattr(sys, 'argv', ['napari', str(script)])
        __main__._run()

    run_path.assert_called_once_with(str(script))


@mock.patch('napari.__main__.view_path')
def test_cli_passes_kwargs(view_path, mock_run, monkeypatch):
    """test that we can parse layer keyword arg variants"""

    with monkeypatch.context() as m:
        m.setattr(sys, 'argv', ['n', 'file', '--name', 'some name'])
        __main__._run()

    view_path.assert_called_once_with(
        ['file'],
        stack=False,
        plugin=None,
        layer_type=None,
        name='some name',
    )
    mock_run.assert_called_once_with(gui_exceptions=True)


def test_cli_retains_viewer_ref(mock_run, monkeypatch):
    """Test that napari.__main__ is retaining a reference to the viewer."""
    v = napari.Viewer(show=False)  # our mock view_path will return this object
    ref_count = None  # counter that will be updated before __main__._run()

    def _check_refs(**kwargs):
        # when run() is called in napari.__main__, we will call this function
        # it forces garbage collection, and then makes sure that at least one
        # additional reference to our viewer exists.
        gc.collect()
        if not sys.getrefcount(v) > ref_count:
            raise AssertionError(
                "Reference to napari.viewer has been lost by "
                "the time the event loop started in napari.__main__"
            )

    mock_run.side_effect = _check_refs
    with monkeypatch.context() as m:
        m.setattr(sys, 'argv', ['napari', 'path/to/file.tif'])
        with mock.patch(
            'napari.__main__.view_path', return_value=v  # return our local v
        ) as mock_vp:
            ref_count = sys.getrefcount(v)  # count current references
            __main__._run()
            mock_vp.assert_called_once()
