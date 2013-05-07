#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division
from gi.repository import Gtk, Gdk
import cairo
from gtkcurvewidget import CurveEditor, Curve, CurveException, interpolationStrategies

# just a preparation for i18n
def _(string):
    return string

class tintValueCMYK(object):
    def __init__(self, name, c=0.0, m=0.0, y=0.0, k=0.0):
        self.name = name
        self.c = c
        self.m = m
        self.y = y
        self.k = k

class displayColor(object):
    def __init__(self, r=0.0, g=0.0, b=0.0):
        self.r = r
        self.g = g
        self.b = b
        
# class Tint(object):
#     def __init__():
#         self.curveType = 
#         self.curve = 
#         self.displayColor
#         self.tintValue

    
class TintList(object):
    def __init__(maxTints = None):
        # its a ghostscript limitation that is used as  delimiter here
        self.maxTints = maxTints if maxTints is not None else float('inf')
        pass

from random import randint
import cairo
from array import array

class CellRendererTint (Gtk.CellRenderer):
    def __init__(self, width=0, height=0):
        Gtk.CellRenderer.__init__(self)
        self.width = width
        self.height = height
        self.rgbbuf = None
    
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
        
        rgbbuf = array('B')
        row = []
        for _ in range(cell_area.width):
            row += [randint(0, 255), randint(0, 255), randint(0, 255), 0]
        for _ in range(cell_area.height):
            rgbbuf.extend(row)
        cairo_surface = cairo.ImageSurface.create_for_data(rgbbuf, cairo.FORMAT_RGB24, cell_area.width, cell_area.height, cell_area.width * 4)
        cr.set_source_surface(cairo_surface, cell_area.x, cell_area.y)
        cr.paint()
    
    def do_get_size(self, widget, cell_area):
        return (0, 0, self.width, self.height)


class TintColumn (Gtk.TreeViewColumn):
    def __init__(self, name, renderer):
        self.renderer = renderer
        Gtk.TreeViewColumn.__init__(self, name, self.renderer)
    
    def onScaleChange(self, scale):
        """ be as wide as the curve widget """
        w, _ = scale()
        if w != self.renderer.width:
            self.renderer.width = w
            self.queue_resize()
    

if __name__ == '__main__':
    w = Gtk.Window()
    w.set_default_size(640, 480)
    # the theme should do so
    w.connect('destroy', Gtk.main_quit)
    
    curveEditor = CurveEditor.new(w)
    # will take all the space it can get
    curveEditor.set_hexpand(True)
    curveEditor.set_vexpand(True)
    # min width is 256
    curveEditor.set_size_request(256, -1)
    
    tintGrid = Gtk.Grid()
    # tintGrid.set_column_homogeneous(True)
    # tintGrid.set_row_homogeneous(True)
    w.add(tintGrid)
    
    
    
    # left : the column number to attach the left side of child to
    # top : the row number to attach the top side of child to
    # width : the number of columns that child will span
    # height : the number of rows that child will span
    tintGrid.attach(curveEditor, 0, 0, 1, 1)
    
    # Model for the tints
    # id, name, curve Type
    tintModel = Gtk.ListStore(int, str, str)
    tintModel.append([0, 'Pantone 666', 'Monotone Cubic'])
    tintModel.append([1, 'Black', 'Spline'])
    tintModel.append([2, 'Red', 'Linear'])
    
    
    #Model for the curveType choices, will be used with GtkCellRendererCombo 
    curveTypesModel = Gtk.ListStore(str, str)
    for key, item in interpolationStrategies:
        curveTypesModel.append([item.name, key])
    def onCurveTypeCellChanged(widget, path, text):
        tintModel[path][2] = text
    
    
    #make a treeview …
    treeview = Gtk.TreeView(model=tintModel)
    treeview.set_reorderable(True)
    treeview.set_rules_hint(True)
    treeview.set_property('headers-visible', False)
    treeSelection = treeview.get_selection()
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
    
    renderer_tint = CellRendererTint(256, 15)
    column_tint = TintColumn(_('Tint'), renderer_tint)
    # hookup the renderer to the scale objects onScaleChange event of the curveEditor
    curveEditor.scale.add(column_tint)
    treeview.append_column(column_tint)
    
    renderer_id = Gtk.CellRendererText()
    column_id = Gtk.TreeViewColumn(_('ID'), renderer_id, text=0)
    treeview.append_column(column_id)
    
    renderer_name = Gtk.CellRendererText()
    column_name = Gtk.TreeViewColumn(_('Name'), renderer_name, text=1)
    treeview.append_column(column_name)
    
    renderer_curveType = Gtk.CellRendererText()
    column_curveType = Gtk.TreeViewColumn(_('Interpolation'), renderer_curveType, text=2)
    treeview.append_column(column_curveType)
    
    treeview.set_hexpand(True)
    # because curveWidget expands with the window size and because
    # tint_column will grow to the size of curveWidget, it is important
    # to decouple the treeview size from the window size. otherwise
    # treeview would be able to make the resize happening in a loop by
    # increasing window size and thus expanding curveWidget
    # adding a scrollbar does this well.
    scrolledContainer = Gtk.ScrolledWindow()
    scrolledContainer.set_hexpand(True)
    scrolledContainer.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
    scrolledContainer.add(treeview)
    
    
    
    tintGrid.attach(scrolledContainer, 0, 1, 2, 1)
    
    tints = [
        [0, 'Pantone 666', 'monotoneCubic'],
        [1, 'Black', 'spline'],
        [2, 'Red', 'linear']
    ]
    
    
    tintOptionsBox = Gtk.Grid(orientation=Gtk.Orientation.VERTICAL)
    
    def onWidgetCurveTypeChange(widget, tintId):
        print 'curve of ', tintId, ' changed to', widget.get_active_id()
    
    def show_tint_options(tintId=None):
       
        tintOptionsBox.foreach(lambda x, _: x.destroy(), None)
        
        if tintId is None:
            info = Gtk.Label(_('Select a Tint from the Table above'))
            tintOptionsBox.add(info)
        else:
            tint = tints[int(tintId)]
            
            widget_id = Gtk.Label(tint[0])
            widget_id.set_halign(Gtk.Align.START)
        
            widget_name = Gtk.Entry()
            widget_name.set_text(tint[1])
            
            widget_curveType = Gtk.ComboBoxText.new()
            widget_curveType.set_model(curveTypesModel)
            widget_curveType.set_id_column(1)
            widget_curveType.set_active_id(tint[2])
            widget_curveType.connect('changed', onWidgetCurveTypeChange, tint[0]);
            
            rgba = Gdk.RGBA(1,0,.5)
            colorButton = Gtk.ColorButton.new_with_rgba(rgba)
            
            ws = (
                Gtk.Label(_('Id')), widget_id,
                Gtk.Label(_('Name')), widget_name,
                Gtk.Label(_('Curve Type')), widget_curveType,
                Gtk.Label(_('Indicator Color')), colorButton
            )
            
            for i, w in enumerate(ws):
                hi = i % 2
                tintOptionsBox.attach(w, hi, i-hi, 1, 1)
                w.set_halign(Gtk.Align.FILL if hi else Gtk.Align.END)
            
            
            
        tintOptionsBox.show_all()
    show_tint_options()
    
    tintGrid.attach(tintOptionsBox, 1, 0, 1, 1)
    
    ###
    curveEditor.appendCurve(Curve(curveEditor.scale, [(0.0,0.0), (0.1, 0.4), (0.2, 0.6), (0.5, 0.2), (0.4, 0.3), (1.0,1.0)]))
    curveEditor.appendCurve(Curve(curveEditor.scale, [(0.0,0.0), (0.1, 0.4), (0.2, 0.6)]))
    
    w.show_all()
    Gtk.main()
