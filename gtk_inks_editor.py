#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division, print_function, unicode_literals

import os
import sys
from gi.repository import Gtk, Gdk, GObject, GdkPixbuf, Pango
import cairo
from weakref import ref as Weakref

from gtk_curve_editor import CurveEditor
from interpolation import interpolation_strategies, interpolation_strategies_dict
from emitter import Emitter
from model import ModelCurves, ModelInk
from ghostscript_workers import GradientWorker, PreviewWorker
from preview import PreviewWindow
from history import History
from compatibility import repair_gsignals, encode, decode, range

__all__ = ['InksEditor']

# just a preparation for i18n
def _(string):
    return string

class CellRendererInk (Gtk.CellRendererText):
    """
    Display a preview gradient for just one color in the TreeView
    
    inheriting from CellRendererText had two advantages
    1. the other GtkTreeWidget is rendered with CellRendererTexts, that
       this widget uses the right height automatically
    2. I couldn't figure out how to set a custom property, so i can reuse
       the "text" property to get the ink id
    for anything else, this could be a Gtk.GtkCellRenderer without objections
    """
    __gsignals__ = repair_gsignals({
        'received-surface': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (GObject.TYPE_INT, ))
    })
    
    def __init__(self, model, gradientWorker, width=-1, height=-1):
        Gtk.CellRendererText.__init__(self)
        model.add(self) #subscribe
        self.gradientWorker = gradientWorker
        self.width = width
        self.height = height
        self.state = {}
        self._setCurves(model)
    
    def _init_ink(self, iid):
        """ init the state for a inkModel"""
        self.state[iid] = {
            'surface':None,
            'timeout':None,
            'waiting': False,
            'update_needed': None
        }
    
    def _setCurves(self, model):
        inks = model.curves
        ids = model.ids
        # remove all missing inks
        for iid in self.state.keys():
            if iid not in ids:
                del self.state[iid]
        # add all new inks
        for iid, inkModel in zip(ids, inks):
            if iid not in self.state:
                self._init_ink(iid)
                self._requestNewSurface(inkModel)
    
    def onModelUpdated(self, model, event, *args):
        if event == 'curveUpdate':
            inkModel = args[0]
            inkEvent = args[1]
            # whitelist, needs probbaly an update when more relevant events occur
            if inkEvent in ('pointUpdate', 'addPoint', 'removePoint',
                            'setPoints', 'interpolationChanged',
                            'cmykChanged', 'nameChanged'):
                self._requestNewSurface(inkModel)
        elif event == 'setCurves':
            self._setCurves(model)
        elif event == 'insertCurve':
            inkModel = args[0]
            iid = inkModel.id
            self._init_ink(iid)
            self._requestNewSurface(inkModel)
        elif event == 'removeCurve':
            inkModel = args[0]
            iid = inkModel.id
            if iid in self.state:
                del self.state[iid]
    
    def _requestNewSurface(self, inkModel):
        """ this will be called very frequently, because generating the
        gradients can take a moment this waits until the last call to this
        method was 300 millisecconds ago and then let the rendering start
        """
        
        iid = inkModel.id
        state = self.state[iid]
        
        # reset the timeout
        if state['timeout'] is not None:
            GObject.source_remove(state['timeout'])
        # schedule a new execution
        state['timeout'] = GObject.timeout_add(
            300, self._updateSurface, Weakref(inkModel))
    
    def _updateSurface(self, weakrefModel):
        inkModel = weakrefModel()
        # see if the model still exists
        if inkModel is None:
            # need to return False, to cancel the timeout
            return False
        iid = inkModel.id
        state = self.state[iid]
        if state['waiting']:
            # we are waiting for a job to finish, so we don't put another
            # job on the queue right now
            state['update_needed'] = weakrefModel
            return False
        state['waiting'] = True
        callback = (self._receiveSurface, iid)
        self.gradientWorker.add_job(callback, inkModel)
        
        # this timout shall not be executed repeatedly, thus returning false
        return False
    
    def _receiveSurface(self, iid, w, h, rowstride, buf):
        if iid not in self.state:
            return
        state = self.state[iid]
        
        cairo_surface = cairo.ImageSurface.create_for_data(
            buf, cairo.FORMAT_RGB24, w, h, rowstride
        )
        state['__keep'] = buf
        state['surface'] = cairo_surface
        state['waiting'] = False
        if state['update_needed'] is not None:
            # while we where waiting another update became due
            inkModel = state['update_needed']() # its a weakref
            state['update_needed'] = None
            if inkModel is not None:
                self._requestNewSurface(inkModel)
        
        #schedule a redraw
        self.emit('received-surface', iid)
    
    def do_render(self, cr, widget, background_area, cell_area, flags):
        """
        self ... a GtkCellRenderer
        cr : a cairo context to draw to
        widget : the widget owning window
        background_area : entire cell area (including tree expanders and maybe padding on the sides)
        cell_area : area normally rendered by a cell renderer
        flags : flags that affect rendering
        """
        # print ('cellRendererInk', cell_area.width, cell_area.height, cell_area.x, cell_area.y)
        iidHash = self.get_property('text')
        iid = int(iidHash)
        cairo_surface = None
        if iid in self.state:
            cairo_surface = self.state[iid]['surface']
        
        width, height = (self.width, cell_area.height)
        
        # x = cell_area.x # this used to be 1 but should have been 0 ??
        # this workaround make this cell renderer useless for other
        # positions than the first cell in a tree, i suppose
        if cairo_surface is not None:
            x = 0
            y = cell_area.y
            ctm = cr.get_matrix()
            cr.translate(width, 0)
            cr.scale(-(width/256), 1)
            for y in range(0+y, height+y):
                cr.set_source_surface(cairo_surface, x , y)
                cr.paint()
            cr.set_matrix(ctm)

class ColorPreviewWidget(Gtk.DrawingArea):
    """
        display a preview gradient of all visible colors using ghostscript
    """
    def __init__(self, model, gradientWorker):
        super(ColorPreviewWidget, self).__init__()
        model.add(self) #subscribe
        self._gradientWorker = gradientWorker
        self._surface = None
        self._timeout = None
        self._waiting = False
        self._update_needed = None
        self._noInks = False
        self.connect('draw' , self.onDraw)
        self._requestNewSurface(model)
    
    def onModelUpdated(self, inksModel, event, *args):
        if len(inksModel.visibleCurves) == 0:
            self._surface = None
            self.queue_draw()
            self._noInks = True
            return
        self._noInks = False
        if event == 'curveUpdate':
            # whitelist, needs probbaly an update when more relevant events occur
            inkEvent = args[1]
            if inkEvent not in ('pointUpdate', 'addPoint', 'removePoint',
                                'setPoints', 'interpolationChanged',
                                'visibleChanged', 'cmykChanged',
                                'nameChanged'):
                return
        self._requestNewSurface(inksModel)
    
    def _requestNewSurface(self, inksModel):
        """ this will be called very frequently, because generating the
        gradients can take a moment this waits until the last call to this
        method was 300 millisecconds ago and then let the rendering start
        """
        
        # reset the timeout
        if self._timeout is not None:
            GObject.source_remove(self._timeout)
        # schedule a new execution
        self._timeout = GObject.timeout_add(
            300, self._updateSurface, Weakref(inksModel))
    
    def _updateSurface(self, weakrefModel):
        inksModel = weakrefModel()
        # see if the model still exists
        if inksModel is None or len(inksModel.visibleCurves) == 0:
            # need to return False, to cancel the timeout
            return False
        
        if self._waiting:
            # we are waiting for a job to finish, so we don't put another
            # job on the queue right now
            self._update_needed =  weakrefModel
            return False
        
        self._waiting = True
        
        callback = (self._receiveSurface, )
        self._gradientWorker.add_job(callback, *inksModel.visibleCurves)
        
        # this timout shall not be executed repeatedly, thus returning false
        return False
    
    def _receiveSurface(self, w, h, rowstride, buf):
        if self._noInks:
            # this may receive a surface after all inks are invisible
            cairo_surface = None
        else:
            cairo_surface = cairo.ImageSurface.create_for_data(
                buf, cairo.FORMAT_RGB24, w, h, rowstride
            )
        
        self._waiting = False
        if self._update_needed is not None:
            # while we where waiting another update became due
            inksModel = self._update_needed() # its a weakref
            self._update_needed = None
            if inksModel is not None:
                self._requestNewSurface(inksModel)
        
        self._surface = cairo_surface
        self.queue_draw()
    
    @staticmethod
    def onDraw(self, cr):
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        cairo_surface = self._surface
        if cairo_surface is not None:
            x = 0
            y = 0
            ctm = cr.get_matrix()
            cr.translate(width, 0)
            cr.scale(-(width/256), 1)
            for y in range(0+y, height+y):
                cr.set_source_surface(cairo_surface, x , y)
                cr.paint()
            cr.set_matrix(ctm)

class HScalingTreeColumnView (Gtk.TreeViewColumn):
    """ 
        a Gtk.TreeViewColumn that scales its width according to the scale
        object it should to be subscribed to.
        
        hookup the renderer to the scale objects on_scale_change:
        scale.add(object of HScalingTreeColumnView)
    """
    def __init__(self, name, renderer, text):
        self.renderer = renderer
        Gtk.TreeViewColumn.__init__(self, name, renderer, text=text)
    
    def on_scale_change(self, scale):
        """ be as wide as the curve widget """
        w, _ = scale()
        if w != self.renderer.width:
            self.renderer.width = w
            self.queue_resize()

class InkControllerException(Exception):
    pass

class InkController(Emitter):
    """
    This is the interface used by the widgets.
    I'm unsure right now if the Widgets should rather emmit events
    that the instance of this class would subscribe to
    The attempt to have control over ModelCurves and a here synchronized
    Gtk.ListStore
    """
    def __init__(self, model):
        Emitter.__init__(self)
        
        self.inks = model
        
        #id, name, interpolation Name (for display), locked, visible
        self.inkListStore = Gtk.ListStore(int, str, str, bool, bool)
        self._setCurves(self.inks)
        self.inks.add(self) #subscribe
    
    def triggerOnChangedInkSelection(self, *args):
        for item in self._subscriptions:
            item.onChangedInkSelection(self, *args)
    
    def changedInkSelectionHandler(self, selection):
        model, paths = selection.get_selected_rows()
        if len(paths):
            path = paths[0]
            inkId = model[path][0]
        else:
            inkId = None
        self.triggerOnChangedInkSelection(inkId)
    
    def toggleVisibilityHandler(self, inkControlPanel, path):
        model = self.getInkByPath(path)
        model.visible = not model.visible
    
    def toggleLockedHandler(self, inkControlPanel, path):
        model = self.getInkByPath(path)
        model.locked = not model.locked
    
    def deleteHandler(self, inkControlPanel, path):
        model = self.getInkByPath(path)
        window = inkControlPanel.get_toplevel()
        
        dialog = Gtk.MessageDialog(window, 0, Gtk.MessageType.QUESTION,
            Gtk.ButtonsType.YES_NO, _('Delete the ink “{0}”?').format(model.name))
        dialog.format_secondary_text(
            _('You will loose all of its properties.'))
        response = dialog.run()
        if response == Gtk.ResponseType.YES:
            self.inks.removeCurve(model)
        dialog.destroy()
    
    def setDisplayColorHandler(self, inkControlPanel, path):
        model = self.getInkByPath(path)
        window = inkControlPanel.get_toplevel()
        
        #open colorchooser Dialog
        dialog = Gtk.ColorChooserDialog(_('Pick a color for the editor widget'), window)
        color = Gdk.RGBA(*model.displayColor)
        dialog.set_rgba(color)
        dialog.run()
        color = dialog.get_rgba()
        rgb = (color.red, color.green, color.blue)
        if rgb != model.displayColor:
            model.displayColor = rgb
        dialog.destroy()
    
    def reorderHandler(self, inkControlPanel, sourcePath, targetPath, before):
        source = self.getInkByPath(sourcePath)
        target = self.getInkByPath(targetPath)
        oldOrder = self.inks.ids
        oldIndex = oldOrder.index(source.id)
        removedSource = oldOrder[0:oldIndex] + oldOrder[oldIndex+1:]
        
        newIndex = oldOrder.index(target.id)
        if not before:
            newIndex += 1
        if oldIndex < newIndex:
            newIndex -= 1
        newOrder = removedSource[0:newIndex] + (source.id, ) + removedSource[newIndex:]
        self.inks.reorderByIdList(newOrder)
    
    def initControlPanel(self):
        # make a treeview …
        inkControlPanel = InkControlPanel(
                          model=self.inkListStore, inkModel=self.inks)
        # inkControlPanel.set_valign(Gtk.Align.END)
        treeSelection = inkControlPanel.get_selection()
        treeSelection.connect('changed', self.changedInkSelectionHandler)
        inkControlPanel.connect('toggle-visibility', self.toggleVisibilityHandler)
        inkControlPanel.connect('toggle-locked', self.toggleLockedHandler)
        inkControlPanel.connect('delete', self.deleteHandler)
        inkControlPanel.connect('set-display-color', self.setDisplayColorHandler)
        inkControlPanel.connect('reorder', self.reorderHandler)
        return inkControlPanel
    
    def initGradientView(self, gradientWorker, scale):
        gradientView = Gtk.TreeView(model=self.inkListStore)
        # gradientView.set_valign(Gtk.Align.END)
        
        # gradientView.set_property('headers-visible', False)
        # the width value is just initial and will change when the scale of
        # the curveEditor changes
        renderer_ink = CellRendererInk(model=self.inks, gradientWorker=gradientWorker, width=256)
        renderer_ink.connect('received-surface', self.queueDrawRow)
        
        column_ink = HScalingTreeColumnView(_('Single Ink Gradients'), renderer_ink, text=0)
        gradientView.append_column(column_ink)
        scale.add(column_ink)
        return gradientView
    
    def queueDrawRow(self, widget, iid):
        """ schedules a redraw """
        row = self._getRowById(iid)
        path = row.path
        itr = self.inkListStore.get_iter(path)
        self.inkListStore.row_changed(path, itr)
    
    def _setCurves(self, model):
        self.inkListStore.clear()
        for curveModel in model.curves:
            self._appendToList(curveModel)
    
    def onModelUpdated(self, model, event, *args):
        if event == 'setCurves':
            self._setCurves(model)
        elif event == 'reorderedCurves':
            modelOrder = args[0]
            oldPosLookup = {}
            for oldpos, row in enumerate(self.inkListStore):
                oldPosLookup[row[0]] = oldpos
            #newOrder[newpos] = oldpos
            newOrder = [oldPosLookup[mid] for mid in modelOrder]
            self.inkListStore.reorder(newOrder)
        elif event == 'insertCurve':
            curveModel = args[0]
            position = args[1]
            self._insertIntoList(curveModel, position)
        elif event == 'removeCurve':
            curveModel = args[0]
            self._removeFromList(curveModel)
        elif event == 'curveUpdate':
            curveModel = args[0]
            curveEvent = args[1]
            self._updateRow(curveModel, curveEvent, args[2:])
    
    def _updateRow(self, curveModel, curveEvent, *args):
        interpolationName = interpolation_strategies_dict[curveModel.interpolation].name
        row = self._getRowByModel(curveModel)
        row[1] = curveModel.name
        row[2] = interpolationName
        row[3] = curveModel.locked
        row[4] = curveModel.visible
    
    def _getRowByModel(self, curveModel):
        inkId = curveModel.id
        return self._getRowById(inkId)
    
    def _getRowById(self, inkId):
        for row in self.inkListStore:
            if row[0] == inkId:
                return row
        raise InkControllerException('Row not found by id {0}'.format(inkId))
        
    def _removeFromList(self, curveModel):
        row = self._getRowByModel(curveModel)
        path = row.path
        itr = self.inkListStore.get_iter(path)
        self.inkListStore.remove(itr)
    
    def _insertIntoList(self, curveModel, position):
        modelId = curveModel.id
        interpolationName = interpolation_strategies_dict[curveModel.interpolation].name
        #id, name, interpolation Name (for display), locked, visible
        row = [modelId, curveModel.name, interpolationName, curveModel.locked, curveModel.visible]
        # when position is -1 this appends
        self.inkListStore.insert(position, row);
    
    def _appendToList(self, curveModel):
        self._insertIntoList(curveModel, -1)
    
    def getInkByPath(self, path):
        row = self.inkListStore[path]
        return self.inks.getById(row[0])

class AddInkButton(Gtk.Button):
    """
    Button to add one more Ink to model
    """
    def __init__(self, model, stockID=None, tooltip=None):
        Gtk.Button.__init__(self)
        if stockID is not None:
            self.set_label(stockID)
            self.set_use_stock(True)
        if tooltip is not None:
            self.set_tooltip_text(tooltip)
        
        # ghostscript doesn't do more as it seems
        self.max_inks = 10 
        
        self.model = model
        self.connect('clicked', self.addInk)
        model.add(self)
    
    def addInk(self, *args):
        if len(self.model) < self.max_inks:
            self.model.appendCurve()
    
    def onModelUpdated(self, model, event, *args):
        if event not in ('removeCurve', 'insertCurve', 'setCurves'):
            return
        active = len(model) < self.max_inks
        self.set_sensitive(active)

class CellRendererPixbufButton(Gtk.CellRendererPixbuf):
    """
    used to render a button in a cell using a Gtk.CellRendererPixbuf
    and emits a "clicked" signal
    """
    __gsignals__ = repair_gsignals({
        'clicked': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (GObject.TYPE_STRING, ))
    })

    def __init__(self):
        Gtk.CellRendererPixbuf.__init__(self)
        self.set_property('mode', Gtk.CellRendererMode.ACTIVATABLE)

    def do_activate(self, event, widget, path, background_area, cell_area,
                    flags):
        self.emit('clicked', path)
        return True # activate event got 'consumed'

class CellRendererEditorColor (CellRendererPixbufButton):
    """
    render the color of the ink that has the id of the "identifier" property
    and emmits a "clicked" signal
    """
    def __init__(self, model):
        CellRendererPixbufButton.__init__(self)
        self.model = model
    
    identifier = GObject.property(type=str, default='')
    
    def do_render(self, cr, widget, background_area, cell_area, flags):
        """
        self ... a GtkCellRenderer
        cr : a cairo context to draw to
        widget : the widget owning window
        background_area : entire cell area (including tree expanders and maybe padding on the sides)
        cell_area : area normally rendered by a cell renderer
        flags : flags that affect rendering
        """
        iid = int(self.get_property('identifier'))
        ink = self.model.getById(iid)
        cr.set_source_rgb(*ink.displayColor)
        width, height  = self.get_fixed_size()
        width = min(width, cell_area.width)
        height = min(height, cell_area.height)
        x = int(cell_area.x + (cell_area.width/2 - width/2))
        y = int(cell_area.y + (cell_area.height/2 - height/2))
        cr.rectangle(x, y, width, height)
        cr.fill()

class CellRendererToggle(Gtk.CellRenderer):
    """
    A cell renderer that renders and can toggle a  property called "active"
    """
    __gsignals__ = repair_gsignals({
        'clicked': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (GObject.TYPE_STRING, ))
    })
    
    #active property
    active = GObject.property(type=bool, default=False)
    
    def __init__(self,  activeIcon, inactiveIcon):
        Gtk.CellRenderer.__init__(self)
        self.set_property('mode', Gtk.CellRendererMode.ACTIVATABLE)
        self.activeIcon = activeIcon
        self.inactiveIcon = inactiveIcon

    def do_activate(self, event, widget, path, background_area, cell_area,
                    flags):
        self.emit('clicked', path)
        return True # activate event got 'consumed'

    def do_render(self, cr, widget, background_area, cell_area, flags):
        """
        self ... a GtkCellRenderer
        cr : a cairo context to draw to
        widget : the widget owning window
        background_area : entire cell area (including tree expanders and maybe padding on the sides)
        cell_area : area normally rendered by a cell renderer
        flags : flags that affect rendering
        """
        active = self.get_property('active')
        if active:
            pixbuf = self.activeIcon
        else:
            pixbuf = self.inactiveIcon
        
        width, height = pixbuf.get_width(), pixbuf.get_height()
        x = int(cell_area.width/2 - width/2) + cell_area.x
        y = int(cell_area.height/2 - height/2) + cell_area.y
        
        Gdk.cairo_set_source_pixbuf(cr, pixbuf, x, y)
        cr.paint()

class InkControlPanel(Gtk.TreeView):
    """
    This is the 'table' with the toggles for lock and visibility, the
    delete button and the editor color chooser. Furthermore this can be
    used to reorder the inks with drag and drop.
    """
    __gsignals__ = repair_gsignals({
          'toggle-visibility': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (
                            # path
                            GObject.TYPE_STRING, ))
        , 'toggle-locked': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (
                            # path
                            GObject.TYPE_STRING, ))
        , 'delete': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (
                            # path
                            GObject.TYPE_STRING, ))
        , 'set-display-color': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (
                            # path
                            GObject.TYPE_STRING, ))
        , 'reorder': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, (
                            # source_path, target_path, before/after
                            GObject.TYPE_STRING, GObject.TYPE_STRING,
                            GObject.TYPE_BOOLEAN))
    })
    
    def __init__(self, inkModel, model, **args):
        Gtk.TreeView.__init__(self, model=model, **args)
        self.set_property('headers-visible', True)
        
        # self.set_reorderable(True)
        # The reordering is implemented by setting up the tree view as a
        # drag source and destination.
        targets = [('text/plain', Gtk.TargetFlags.SAME_WIDGET, 0)]
        self.enable_model_drag_source(Gdk.ModifierType.BUTTON1_MASK, targets, Gdk.DragAction.MOVE)
        self.enable_model_drag_dest(targets, Gdk.DragAction.MOVE)
        self.connect('drag-data-received', self.dragDataReceivedHandler)
        self.connect('drag-data-get', self.dragDataGetHandler)
        
        def initColumnId():
            return self._initColumnId(inkModel)
        
        for initiate in (initColumnId, self._initColumnName,
                         self._initColumnCurveType):
            column = initiate()
            self.append_column(column)
    
    @staticmethod
    def dragDataGetHandler(treeview, context, selection, info, timestamp):
        # the easiest way seems to assume that the row beeing dropped
        # is the selected row
        model, iter = treeview.get_selection().get_selected()
        path = str(model.get_path(iter))
        selection.set(selection.get_target(), 8, path)
        return
    
    @staticmethod
    def dragDataReceivedHandler(treeview, context, x, y, data, info, time, *user_data):
        """
        Atguments:
        GdkDragContext   context    <gtk.gdk.X11DragContext object at 0x325ad70 (GdkX11DragContext at 0x35fdd30)>,
        gint             x          171,
        gint             y          68,
        GtkSelectionData *data      <GtkSelectionData at 0x7fff1c9796c0>,
        guint            info       0L,
        guint            time       4785524L
                         *user_data
        """
        source_path = Gtk.TreePath.new_from_string(data.get_data())
        target_path, drop_position = treeview.get_dest_row_at_pos(x, y)
        # drop_positions:
        #     # both before
        beforePositions = (Gtk.TreeViewDropPosition.BEFORE, Gtk.TreeViewDropPosition.INTO_OR_BEFORE)
        afterPositions = (Gtk.TreeViewDropPosition.AFTER, Gtk.TreeViewDropPosition.INTO_OR_AFTER)
        if drop_position in beforePositions:
            before = True
        elif drop_position in afterPositions:
            before = False
        else:
            warn('drop position is neither before nor after {0}'.format(drop_position))
            return
        
        treeview.emit('reorder', source_path, target_path, before)
        context.finish(success=True, del_=False, time=time)
    
    def _initToggle(self, icons, callback, *data):
        setup = {}
        for key, fileName in icons.items():
            iconPath = os.path.join(os.path.dirname(__file__), encode('icons'), encode(fileName))
            setup[key] = GdkPixbuf.Pixbuf.new_from_file_at_size(iconPath, 16, 16)
        toggle = CellRendererToggle(**setup)
        toggle.set_fixed_size (16, 16)
        toggle.connect('clicked', callback, *data)
        return toggle
    
    def trigger(self, cellRenderer, path, signalName):
        self.emit(signalName, path)
    
    def _initEditorColorInterface(self, model):
        editorColor = CellRendererEditorColor(model=model)
        editorColor.set_fixed_size(16,16)
        editorColor.connect('clicked', self.trigger, 'set-display-color')
        return editorColor;
    
    def _initVisibilityToggle(self):
        icons = {'activeIcon': 'visible.svg', 'inactiveIcon': 'invisible.svg'}
        return self._initToggle(icons, self.trigger, 'toggle-visibility')
    
    def _initLockedToggle(self):
        icons = {'activeIcon': 'locked.svg', 'inactiveIcon': 'unlocked.svg'}
        return self._initToggle(icons, self.trigger, 'toggle-locked')
    
    def _initDeleteButton(self):
        button = CellRendererPixbufButton()
        button.set_property('stock-id', Gtk.STOCK_DELETE)
        button.connect('clicked', self.trigger, 'delete')
        return button;
    
    def _initColumnId(self, model):
        column = Gtk.TreeViewColumn(_('Tools'))
        
        visibilityToggle = self._initVisibilityToggle()
        lockedToggle = self._initLockedToggle()
        deleteButton = self._initDeleteButton()
        editorColor = self._initEditorColorInterface(model)
        
        column.pack_start(visibilityToggle, False)
        column.pack_start(lockedToggle, False)
        column.pack_start(editorColor, False)
        column.pack_start(deleteButton, False)
    
        column.add_attribute(editorColor, 'identifier', 0)
        column.add_attribute(lockedToggle, 'active', 3)
        column.add_attribute(visibilityToggle, 'active', 4)
        return column;
    
    def _initColumnName(self):
        renderer = Gtk.CellRendererText()
        renderer.set_property('ellipsize', Pango.EllipsizeMode.END)
        column = Gtk.TreeViewColumn(_('Name'), renderer, text=1)
        column.set_property('resizable', True)
        column.set_property('min-width', 120)
        return column
        
    def _initColumnCurveType(self):
        renderer = Gtk.CellRendererText()
        renderer.set_property('ellipsize', Pango.EllipsizeMode.END)
        column = Gtk.TreeViewColumn(_('Interpolation'), renderer, text=2)
        column.set_property('resizable', True)
        column.set_property('min-width', 120)
        return column

class InkSetup(object):
    """
    This is the Interface to change the setup of an ink
    
    todo: this should subscribe to model
    """
    def __init__(self, model):
        self.model = model
        model.add(self)
        
        self.gtk = frame = Gtk.Box()
        self._inkOptionsBox = Gtk.Grid()
        self._inkOptionsBox.set_halign(Gtk.Align.FILL)
        self._inkOptionsBox.set_hexpand(True)
        self._inkOptionsBox.set_column_spacing(5)
        self._inkOptionsBox.set_row_spacing(5)
        
        frame.add(self._inkOptionsBox)
        frame.set_hexpand(False)
        # this is about the focus-in-event
        # From the docs:
        # To receive this signal, the GdkWindow associated to the widget needs
        # to enable the GDK_FOCUS_CHANGE_MASK mask. 
        # This is done on init using self.gtk.add_events (0 | Gdk.EventMask.FOCUS_CHANGE_MASK)
        # however, since it worked before I have no prove that this is done
        # right, so when it breaks some day, look here
        self.gtk.add_events (0 | Gdk.EventMask.FOCUS_CHANGE_MASK)
        self._interpolations = Gtk.ListStore(str, str)
        for key, item in interpolation_strategies:
            self._interpolations.append([item.name, key])
        
        self._currentInkId = None
        # events show() connected to
        self._connected = [];
        self._widgets = {}
        self.show();
    
    def onModelUpdated(self, model, event, *args):
        if event != 'curveUpdate':
            return
        ink = args[0]
        inkEvent = args[1]
        if self._currentInkId != ink.id:
            return
        # note that all gtk handlers are blocked during setting the values
        # this prevents the loop where the model is updated with the very
        # same changes it just triggert
        if inkEvent == 'nameChanged':
            widget, handler_id = self._widgets['name']
            if decode(widget.get_text()) != ink.name:
                widget.handler_block(handler_id)
                widget.set_text(ink.name)
                widget.handler_unblock(handler_id)
        elif inkEvent == 'cmykChanged':
            for attr in ('c', 'm', 'y', 'k'):
                widget, handler_id = self._widgets[attr]
                adjustment = widget.get_adjustment()
                value = getattr(ink, attr)
                if adjustment.get_value() == value:
                    continue
                widget.handler_block(handler_id)
                adjustment.set_value(value)
                widget.handler_unblock(handler_id)
        elif inkEvent == 'interpolationChanged':
            widget, handler_id = self._widgets['curveType']
            widget.handler_block(handler_id)
            widget.set_active_id(ink.interpolation)
            widget.handler_unblock(handler_id)
    
    def show(self, inkId=None):
        if inkId is None:
            # just disable, this prevents the size of the box from changing
            # and it tells the ui story somehow right, or?
            # self._inkOptionsBox.set_sensitive(False)
            self._inkOptionsBox.hide()
        else:
            self._currentInkId = inkId
            ink = self.model.getById(inkId)
            # the 'value-changed' Signal of Gtk.SpinButton fired on calling
            # its destroy method when it had focus (cursor blinking inside
            # the textbox) with a value of 0 and so deleted the actual value
            for widget, handler_id in self._widgets.values():
                widget.disconnect(handler_id)
            
            self._widgets = {}
            widgets = self._widgets
            
            self._inkOptionsBox.foreach(lambda x, _: x.destroy(), None)
            self._inkOptionsBox.set_sensitive(True)
            inkId = ink.id
            
            label = Gtk.Label(_('Ink Setup'))
            label.get_style_context().add_class('headline')
            label.set_halign(Gtk.Align.START)
            separator = Gtk.Separator()
            self._inkOptionsBox.attach(separator, 0, -2, 2, 1)
            self._inkOptionsBox.attach(label, 0, -1, 2, 1)
            # make the name widget
            widget = Gtk.Entry()
            widget.set_text(ink.name)
            handler_id = widget.connect('changed', self.onNameChange, inkId);
            widget.connect('focus-in-event', self.focusInHandler, inkId)
            widgets['name'] = (widget, handler_id)
            
            # make the interpolation type widget
            widget = Gtk.ComboBoxText.new()
            widget.set_model(self._interpolations)
            widget.set_id_column(1)
            widget.set_active_id(ink.interpolation)
            handler_id = widget.connect('changed', self.onCurveTypeChange, inkId);
            widgets['curveType'] = (widget, handler_id)
            
            # insert the name and the interpolation type widget with labels
            ws = [
                Gtk.Label(_('Name')), widgets['name'][0],
                Gtk.Label(_('Curve Type')), widgets['curveType'][0],
            ]
            for i, w in enumerate(ws):
                hi = i % 2
                self._inkOptionsBox.attach(w, hi, (i-hi)/2, 1, 1)
                w.set_halign(Gtk.Align.FILL if hi else Gtk.Align.START)
            
            # make and insert the cmyk widgets
            offset = len(ws)
            for i, (colorAttr, label) in enumerate([('c',_('C')),('m',_('M')),('y',_('Y')),('k', _('K'))]):
                w = Gtk.Label(label)
                w.set_halign(Gtk.Align.START)
                self._inkOptionsBox.attach(w, 0,i+offset, 1, 1)
                
                # value: the initial value.
                # lower : the minimum value.
                # upper : the maximum value.
                # step_increment : the step increment.
                # page_increment : the page increment.
                # page_size : The page size of the adjustment.
                value = getattr(ink, colorAttr)
                adjustment = Gtk.Adjustment(value, 0.0, 1.0, 0.0001,0.01, 0.0)
                widget = Gtk.SpinButton(digits=4, climb_rate=0.0001, adjustment=adjustment)
                widget.set_halign(Gtk.Align.FILL)
                handler_id = widget.connect('value-changed', self.onCMYKValueChange, inkId, colorAttr)
                widget.connect('focus-in-event', self.focusInHandler, inkId)
                self._inkOptionsBox.attach(widget, 1, i+offset, 1, 1)
                widgets[colorAttr] = (widget, handler_id)
            for widget, __ in widgets.values():
                widget.set_hexpand(True)
            self._inkOptionsBox.show_all()
        
    def focusInHandler(self, widget, __, inkId):
        self.model.getById(inkId).register_consecutive_command()
    
    def onCurveTypeChange(self, widget, inkId):
        ink = self.model.getById(inkId)
        interpolation = widget.get_active_id()
        ink.interpolation = interpolation
    
    def onNameChange(self, widget, inkId):
        ink = self.model.getById(inkId)
        name = decode(widget.get_text())
        ink.name = name
    
    def onCMYKValueChange(self, widget, inkId, colorAttr):
        ink = self.model.getById(inkId)
        value = widget.get_adjustment().get_value()
        setattr(ink, colorAttr,  value)

class InksEditor(Gtk.Grid):
    __gsignals__ = repair_gsignals({
          'open-preview': (GObject.SIGNAL_RUN_LAST, GObject.TYPE_NONE, 
                            # nothing
                            ())
    })
    
    
    def __init__(self, model, gradientWorker):
        """
        gradientWorker: a initialized GradientWorker
        """
        Gtk.Grid.__init__(self)
        self.set_column_spacing(5)
        self.set_row_spacing(5)
        
        self.inkController = InkController(model)
        
        curveEditor = self.initCurveEditor(model)
        
        toolColumn = Gtk.Grid()
        toolColumn.set_row_spacing(5)
        
        
        # its important to keep a reference of this, otherwise its __dict__
        # gets lost and the InkSetup won't know its model anymore
        # this is a phenomen with gtk
        self.inkSetup = inkSetup = self.initInkSetup(model);
        # todo: the selection could and maybe should be part of the
        # model data. Then the inksetup could just subscribe to
        # onModelUpdated
        def onChangedInkSelection(inkController, inkId=None):
            """ callback for the inkController event """
            inkSetup.show(inkId)
        inkSetup.onChangedInkSelection = onChangedInkSelection
        self.inkController.add(inkSetup) # subscribe
        
        inkControlPanel = self.inkController.initControlPanel()
        
        # scales to the width of curveEditor.scale
        gradientView = self.inkController.initGradientView(
                       gradientWorker, curveEditor.scale)
        
        colorPreviewWidget = self.initColorPreviewWidget(model, gradientWorker)
        
        colorPreviewLabel = self.initColorPreviewLabel()
        openPreviewButton = self.initOpenPreviewButton()
        addInkButton = self.initAddInkButton(model)
        
        # left : the column number to attach the left side of child to
        # top : the row number to attach the top side of child to
        # width : the number of columns that child will span
        # height : the number of rows that child will span
        self.attach(toolColumn, 0, 0, 1, 3)
        
        self.attach(curveEditor,        2, 2, 1, 1)
        self.attach(gradientView,       2, 0, 1, 1)
        self.attach(colorPreviewWidget, 2, 1, 1, 1)
        
        toolColumn.attach(inkSetup.gtk,      0, 2, 1, 1)
        toolColumn.attach(inkControlPanel,   0, 0, 1, 1)
        
        
        toolColumn.attach(addInkButton,      0, 1, 1, 1)
        toolColumn.attach(openPreviewButton, 0, 1, 1, 1)
        toolColumn.attach(colorPreviewLabel, 0, 1, 1, 1)
        
    def initCurveEditor(self, model):
        curveEditor = CurveEditor.new(model)
        # will take all the space it can get
        curveEditor.set_hexpand(True)
        curveEditor.set_vexpand(True)
        # min width is 256
        curveEditor.set_size_request(256, -1)
        
        self.add_events(Gdk.EventMask.KEY_PRESS_MASK | Gdk.EventMask.KEY_RELEASE_MASK)
        self.connect('key-press-event'     , curveEditor.key_press_handler)
        self.connect('key-release-event'   , curveEditor.key_release_handler)
        
        return curveEditor
    
    def initInkSetup(self, model):
        inkSetup = InkSetup(model)
        inkSetup.gtk.set_valign(Gtk.Align.FILL)
        inkSetup.gtk.set_vexpand(True) # so this pushes itself to the bottom
        return inkSetup;
    
    def initColorPreviewWidget(self, model, gradientWorker):
        widget = ColorPreviewWidget(model, gradientWorker)
        widget.set_hexpand(True)
        widget.set_vexpand(False)
        # set min height
        widget.set_size_request(-1, 30)
        return widget
    
    def initColorPreviewLabel(self):
        label = Gtk.Label(_('Result:'))
        label.set_halign(Gtk.Align.END)
        return label
    
    def initAddInkButton(self, model):
        button = AddInkButton(model, Gtk.STOCK_ADD, _('Add a new ink'))
        button.set_halign(Gtk.Align.START)
        return button
    
    def initOpenPreviewButton(self):
        # label 
        label = Gtk.Grid()
        # label icon
        icon = Gtk.Image.new_from_stock(Gtk.STOCK_PRINT_PREVIEW, Gtk.IconSize.BUTTON)
        label.attach(icon, 0, 0, 1, 1)
        # label text
        text = Gtk.Label(' ' + _('Open Preview'))
        label.attach_next_to(text, icon, Gtk.PositionType.RIGHT, 1, 1)
        
        button = Gtk.Button()
        button.add(label)
        button.set_tooltip_text(_('Open a Preview Window'))
        
        def clicked_handler(widget):
            self.emit('open-preview')
        button.connect('clicked', clicked_handler)
        button.set_halign(Gtk.Align.CENTER)
        return button

if __name__ == '__main__':
    import sys
    GObject.threads_init()
    use_gui, __ = Gtk.init_check(sys.argv)
    window = Gtk.Window()
    
    cssProvider = Gtk.CssProvider()
    cssProvider.load_from_path('style.css')
    screen = window.get_screen()
    styleContext = Gtk.StyleContext()
    styleContext.add_provider_for_screen(screen, cssProvider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
    
    window.set_title(_('Ink Tool'))
    window.set_default_size(640, 480)
    window.set_has_resize_grip(True)
    # the theme should do so
    window.set_border_width(5)
    
    window.connect('destroy', Gtk.main_quit)
    
    model = ModelCurves(ChildModel=ModelInk)
    history = History(model)
    gradientWorker = GradientWorker.new_with_pool()
    inksEditor = InksEditor(model, gradientWorker)
    
    window.add(inksEditor)
    
    
    ####
    def ctrlHistory(widget, action):
        getattr(history, action)()
    
    undoButton = Gtk.Button()
    undoButton.set_label('gtk-undo')
    undoButton.set_use_stock(True)
    undoButton.connect('clicked', ctrlHistory, 'undo')
    
    redoButton = Gtk.Button()
    redoButton.set_label('gtk-redo')
    redoButton.set_use_stock(True)
    redoButton.connect('clicked', ctrlHistory, 'redo')
    
    inksEditor.attach(undoButton, 0, -1, 1, 1)
    inksEditor.attach(redoButton, 2, -1, 1, 1)
    
    ##### preview Window
    previewWorker = None
    def open_preview(imageName=None):
        global previewWorker
        if previewWorker is None:
            previewWorker = PreviewWorker(gradientWorker.pool) # shares the pool
        previewWindow = PreviewWindow(previewWorker, model, imageName)
        previewWindow.show_all()
        if imageName is None:
            previewWindow.askForImage()
    
    def request_preview_handler(widget, *user_data):
        open_preview()
    
    inksEditor.connect('open-preview', request_preview_handler)
    
    ##
    if len(sys.argv) > 1:
        imageName = sys.argv[1]
        open_preview(imageName)
    
    # fixture for development
    initInks = [
        {
            'locked': True,
            'name': 'PANTONE 406 C',
            'displayColor': (0.8233333333333334, 0.7876555555555557, 0.7876555555555557),
            'cmyk': (0.05, 0.09, 0.1, 0.13),
            'visible': True,
            'points': [(0, 0.13370473537604458), (1, 0.45403899721448465), (0.18808777429467086, 0.2590529247910863)],
            'interpolation': 'monotoneCubic'
        },
        {
            'locked': False,
            'name': 'PANTONE 409 C',
            'displayColor': (0.5333333333333333, 0.5411764705882353, 0.5215686274509804),
            'cmyk': (0.16, 0.25, 0.21, 0.45),
            'visible': True,
            'points': [(0, 0), (0.38557993730407525, 0.22841225626740946), (0.7084639498432602, 0.6434540389972145), (1, 0.8495821727019499)],
            'interpolation': 'linear'
        },
        {
            'locked': False,
            'name': 'Black',
            'displayColor': (0, 0, 0),
            'cmyk': (0.0, 0.0, 0.0, 0.0),
            'visible': True,
            'points': [(0.4890282131661442, 0), (1, 1), (0, 0), (0.780564263322884, 0.6295264623955432)],
            'interpolation': 'spline'
        }
    ]
    
    for t in initInks:
        model.appendCurve(t)
    
    window.show_all()
    Gtk.main()
