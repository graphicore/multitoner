#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division
from gi.repository import Gtk, Gdk
import cairo
from gtkcurvewidget import CurveEditor, CurveException
from interpolation import interpolationStrategies, interpolationStrategiesDict
from model import ModelCurves, ModelTint

# just a preparation for i18n
def _(string):
    return string
    
class TintList(object):
    def __init__(maxTints = None):
        # its a ghostscript limitation that is used as  delimiter here
        self.maxTints = maxTints if maxTints is not None else float('inf')
        pass

import cairo
from array import array

class CellRendererTint (Gtk.CellRendererText):
    """
    inheriting from CellRendererText had two advantages
    1. the other GtkTreeWidget is rendered with CellRendererTexts, that
       this widget uses the right height automatically
    2. I couldn't figure out how to set a custom property, so i can reuse
       the "text" property to get the tint id
    for anything else, this could be a Gtk.GtkCellRenderer without objections
    """
    def __init__(self, ctrl, width=-1, height=-1):
        Gtk.CellRendererText.__init__(self)
        self.ctrl = ctrl
        self.width = width
        self.height = height
    
    def do_render(self, cr, widget, background_area, cell_area, flags):
        """
        self ... a GtkCellRenderer
        cr : a cairo context to draw to
        widget : the widget owning window
        background_area : entire cell area (including tree expanders and maybe padding on the sides)
        cell_area : area normally rendered by a cell renderer
        flags : flags that affect rendering
        """
        # print 'cellRendererTint', cell_area.width, cell_area.height, cell_area.x, cell_area.y
        tid = int(self.get_property('text'))
        tint = self.ctrl.getTintById(tid)
        color = tint.displayColor
        rgbbuf = array('B')
        row = []
        ip = interpolationStrategiesDict[tint.interpolation](tint.pointsValue)
        for i in range(self.width):
            pos = max(0.0, min(1.0, ip(i/self.width)))
            ff = 255 * (1-pos)
            oo = 255 * pos
            row += [
                int(ff + oo * color[2]),
                int(ff + oo * color[1]),
                int(ff + oo * color[0]),
                0
                ]
        for _ in range(cell_area.height):
            rgbbuf.extend(row)
        cairo_surface = cairo.ImageSurface.create_for_data(rgbbuf, cairo.FORMAT_RGB24, self.width, cell_area.height, self.width * 4)
        # x = cell_area.x # this used to be 1 but should have been 0 ??
        # this workaround make this cell renderer useless for other
        # positions than the first cell in a tree, i suppose
        x = 0
        y = cell_area.y
        cr.set_source_surface(cairo_surface, x , y)
        cr.paint()
    
    #def do_get_size(self, widget, cell_area):
    #    return (0, 0, self.width, self.height)
    def do_get_preferred_size(self, widget):
        
        return (
            Gtk.Requisition(self.width, self.height),
            Gtk.Requisition(self.width, self.height)
        )

class CellRendererEditorColor (Gtk.CellRendererText):
    """
    inheriting from CellRendererText had two advantages
    1. the other GtkTreeWidget is rendered with CellRendererTexts, that
       this widget uses the right height automatically
    2. I couldn't figure out how to set a custom property, so i can reuse
       the "text" property to get the tint id
    for anything else, this could be a Gtk.GtkCellRenderer without objections
    """
    def __init__(self, ctrl):
        Gtk.CellRendererText.__init__(self)
        self.ctrl = ctrl
    
    def do_render(self, cr, widget, background_area, cell_area, flags):
        """
        self ... a GtkCellRenderer
        cr : a cairo context to draw to
        widget : the widget owning window
        background_area : entire cell area (including tree expanders and maybe padding on the sides)
        cell_area : area normally rendered by a cell renderer
        flags : flags that affect rendering
        """
        tid = int(self.get_property('text'))
        tint = self.ctrl.getTintById(tid)
        cr.set_source_rgb(*tint.displayColor)
        width, height  = self.get_fixed_size()
        width = min(width, cell_area.width)
        height = min(height, cell_area.height)
        x = int(cell_area.x + (cell_area.width/2 - width/2))
        y = int(cell_area.y + (cell_area.height/2 - height/2))
        cr.rectangle(x, y, width, height)
        cr.fill()

class TintColumnView (Gtk.TreeViewColumn):
    def __init__(self, name, renderer, scale, text):
        self.renderer = renderer
        # hookup the renderer to the scale objects onScaleChange event of the curveEditor
        scale.add(self)
        #self.scale  = scale
        
        Gtk.TreeViewColumn.__init__(self, name, self.renderer, text=text)
    
    def onScaleChange(self, scale):
        """ be as wide as the curve widget """
        w, _ = scale()
        if w != self.renderer.width:
            self.renderer.width = w
            self.queue_resize()

class TintControllerException(Exception):
    pass

class TintController(object):
    def __init__(self, curves=[]):
        self.tints = ModelCurves(ChildModel=ModelTint)
        #id, name, interpolation Name (for display) 
        self.tintListStore = Gtk.ListStore(int, str, str)
        
        self.tintListStore.connect('row_deleted', self.onRowDeleted)
        
        self.tints.add(self) #subscribe
        self.tints.curves = curves
    
    def onRowDeleted(self, *args):
        """
        we use this to reorder the curves
        """
        newOrder = []
        for row in self.tintListStore:
            newOrder.append(row[0])
        self.tints.reorderByIdList(newOrder)
    
    def onModelUpdated(self, model, event, *args):
        if event == 'setCurves':
            self.tintListStore.clear()
            for curveModel in self.tints.curves:
                self._appendToList(curveModel)
        elif event == 'appendCurve':
            curveModel = args[0]
            self._appendToList(curveModel)
        elif event == 'removeCurve':
            pass
        elif event == 'curveUpdate':
            curveModel = args[0]
            curveEvent = args[1]
            self._updateRow(curveModel, curveEvent, args[2:])
    
    def _updateRow(self, curveModel, curveEvent, *args):
        interpolationName = interpolationStrategiesDict[curveModel.interpolation].name
        row = self._getRowByModel(curveModel)
        row[1] = curveModel.name
        row[2] = interpolationName
    
    def _getRowByModel(self, curveModel):
        tintId = id(curveModel)
        for row in self.tintListStore:
            if row[0] == tintId:
                return row
        raise TintControllerException('Row not found by id {0}'.format(tintId))
    
    def _appendToList(self, curveModel):
        modelId = id(curveModel)
        interpolationName = interpolationStrategiesDict[curveModel.interpolation].name
        self.tintListStore.append([modelId, curveModel.name, interpolationName])
        
    def getTintById(self, tintId):
        for curveModel in self.tints.curves:
            if id(curveModel) == tintId:
                return curveModel
        raise TintControllerException('Tint not found by id {0}'.format(tintId))
        

#Model for the curveType choices, will be used with GtkCellRendererCombo 
interpolationStrategiesListStore = Gtk.ListStore(str, str)
for key, item in interpolationStrategies:
    interpolationStrategiesListStore.append([item.name, key])
        
if __name__ == '__main__':
    w = Gtk.Window()
    
    cssProvider = Gtk.CssProvider()
    cssProvider.load_from_path('style.css')
    screen = w.get_screen()
    styleContext = Gtk.StyleContext()
    styleContext.add_provider_for_screen(screen, cssProvider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
    
    w.set_name('win')
    w.set_default_size(640, 480)
    w.set_has_resize_grip(True)
    # the theme should do so
    w.set_border_width(5)
    
    w.connect('destroy', Gtk.main_quit)
    
    
    tintController = TintController()
    
    
    
    curveEditor = CurveEditor.new(w, tintController.tints)
    # will take all the space it can get
    curveEditor.set_hexpand(True)
    curveEditor.set_vexpand(True)
    # min width is 256
    curveEditor.set_size_request(256, -1)
    
    tintGrid = Gtk.Grid()
    tintGrid.set_column_spacing(5)
    # tintGrid.set_column_homogeneous(True)
    # tintGrid.set_row_homogeneous(True)
    w.add(tintGrid)
    
    # left : the column number to attach the left side of child to
    # top : the row number to attach the top side of child to
    # width : the number of columns that child will span
    # height : the number of rows that child will span
    tintGrid.attach(curveEditor, 0, 0, 1, 1)
    
    
    # make a treeview …
    controlView = Gtk.TreeView(model=tintController.tintListStore)
    controlView.set_reorderable(True)
    controlView.set_property('headers-visible', True)
    
    treeSelection = controlView.get_selection()
    def onChangedSelection(selection):
        model, paths = selection.get_selected_rows()
        if len(paths):
            path = paths[0]
            selected = model[path][0]
        else:
            selected = None
        show_tint_options(selected)
        print 'selected is', selected
    treeSelection.connect("changed", onChangedSelection)
    
    gradientView = Gtk.TreeView(model=tintController.tintListStore)
    gradientView.set_property('headers-visible', False)
    
    # the width value is just initial and will change when the scale of
    # the curveEditor changes
    renderer_tint = CellRendererTint(ctrl=tintController,width=256)
    column_tint = TintColumnView(_('Tint'), renderer_tint, scale=curveEditor.scale, text=0)
    gradientView.append_column(column_tint)
    
    renderer_editorColor = CellRendererEditorColor(ctrl=tintController)
    renderer_editorColor.set_fixed_size (15,15)
    column_id = Gtk.TreeViewColumn(_('ID'), renderer_editorColor, text=0)
    controlView.append_column(column_id)
    
    renderer_name = Gtk.CellRendererText()
    column_name = Gtk.TreeViewColumn(_('Name'), renderer_name, text=1)
    controlView.append_column(column_name)
    
    renderer_curveType = Gtk.CellRendererText()
    column_curveType = Gtk.TreeViewColumn(_('Interpolation'), renderer_curveType, text=2)
    controlView.append_column(column_curveType)
    
    controlView.set_valign(Gtk.Align.END)
    #controlView.set_vexpand(True) # so this pushes itself to the bottom
    gradientView.set_valign(Gtk.Align.END)
    
    
    tintGrid.attach(gradientView, 0, 1, 1, 1)
    rightColumn = Gtk.Grid()
    rightColumn.set_row_spacing(5)
    rightColumn.attach(controlView, 0, 1, 1, 1)
    tintGrid.attach(rightColumn, 1, 0, 1, 2)
    
    tintOptionsBox = Gtk.Grid(orientation=Gtk.Orientation.VERTICAL)
    
    
    frame = Gtk.Frame()
    frame.set_label(_('Tint Setup'))
    frame.set_valign(Gtk.Align.FILL)
    frame.add(tintOptionsBox)
    frame.set_vexpand(True) # so this pushes itself to the bottom
    
    rightColumn.attach(frame, 0, 0, 1, 1)
    
    
    def onWidgetCurveTypeChange(widget, tintId):
        interpolation = widget.get_active_id()
        tintController.getTintById(tintId).interpolation = interpolation
    
    def onWidgetNameChange(widget, tintId):
        name = widget.get_text()
        tintController.getTintById(tintId).name = name
    
    def onWidgetColorChange(widget, tintId):
        color = widget.get_rgba()
        rgb = (color.red, color.green, color.blue)
        tintController.getTintById(tintId).displayColor = rgb
    
    def onWidgetCMYKValueChange(widget, tintId, colorAttr):
        tint = tintController.getTintById(tintId)
        value = widget.get_adjustment().get_value()
        setattr(tint, colorAttr,  value)
    
    def show_tint_options(tintId=None):
        tintOptionsBox.foreach(lambda x, _: x.destroy(), None)
        
        if tintId is None:
            info = Gtk.Label(_('- No tint selected -'))
            tintOptionsBox.add(info)
        else:
            tint = tintController.getTintById(tintId)
            
            widget_id = Gtk.Label(tintId)
            widget_id.set_halign(Gtk.Align.START)
        
            widget_name = Gtk.Entry()
            widget_name.set_text(tint.name)
            widget_name.connect('changed', onWidgetNameChange, tintId);
            
            widget_curveType = Gtk.ComboBoxText.new()
            widget_curveType.set_model(interpolationStrategiesListStore)
            widget_curveType.set_id_column(1)
            widget_curveType.set_active_id(tint.interpolation)
            widget_curveType.connect('changed', onWidgetCurveTypeChange, tintId);
            
            rgba = Gdk.RGBA(*tint.displayColor)
            colorButton = Gtk.ColorButton.new_with_rgba(rgba)
            colorButton.connect('color-set', onWidgetColorChange, tintId);
            
            ws = [
                Gtk.Label(_('Id')), widget_id,
                Gtk.Label(_('Name')), widget_name,
                Gtk.Label(_('Curve Type')), widget_curveType,
                Gtk.Label(_('Editor Color')), colorButton
            ]
            
            
            for i, w in enumerate(ws):
                hi = i % 2
                tintOptionsBox.attach(w, hi, (i-hi)/2, 1, 1)
                w.set_halign(Gtk.Align.FILL if hi else Gtk.Align.START)
            
            offset = len(ws)
            for i, (colorAttr, label) in enumerate([('c',_('C')),('m',_('M')),('y',_('Y')),('k', _('K'))]):
                w = Gtk.Label(label)
                w.set_halign(Gtk.Align.START)
                tintOptionsBox.attach(w, 0,i+offset, 1, 1)
                
                # value: the initial value.
                # lower : the minimum value.
                # upper : the maximum value.
                # step_increment : the step increment.
                # page_increment : the page increment.
                # page_size : The page size of the adjustment.
                value = getattr(tint, colorAttr)
                adjustment = Gtk.Adjustment(value, 0.0, 1.0, 0.0001,0.01, 0.1)
                entry = Gtk.SpinButton(digits=4, climb_rate=0.0001, adjustment=adjustment)
                entry.set_halign(Gtk.Align.FILL)
                entry.connect('value-changed', onWidgetCMYKValueChange,tintId, colorAttr)
                tintOptionsBox.attach(entry, 1, i+offset, 1, 1)
                
                
                
            
        tintOptionsBox.show_all()
    show_tint_options()
    
    
    
    ###
    tintController.tints.appendCurve(points=[(0.0, 0.0), (0.1, 0.4), (0.2, 0.6), (0.5, 0.2), (0.4, 0.3), (1.0,1.0)])
    tintController.tints.appendCurve(points=[(0.0, 0.0), (0.1, 0.4), (0.2, 0.6)], interpolation='spline')
    w.show_all()
    Gtk.main()
