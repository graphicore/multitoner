#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import division, print_function, unicode_literals

from gi.repository import Gtk

from gtk_actiongroup import ActionGroup
from gtk_dialogs import show_open_image_dialog, show_message, show_save_as_dialog, \
                    show_save_as_eps_dialog
from gtk_document import Document

from ghostscript_workers import factory as gs_workers_factory
from mtt2eps import model2eps


__all__ = ['Multitoner']


# just a preparation for i18n
def _(string):
    return string


UI_INFO = """
<ui>
  <menubar name='MenuBar'>
    <menu action='FileMenu'>
      <menuitem action='FileNew' />
      <separator />
      <menuitem action='FileOpen' />
      <menuitem action='FileOpenRecent' />
      <separator />
      <menuitem action='FileSaveDocument' />
      <menuitem action='FileSaveAsDocument' />
      <menuitem action='FileSaveAll' />
      <separator />
      <menuitem action='FileExportImage' />
      <separator />
      <menuitem action='FileClose' />
      <menuitem action='FileCloseOther' />
      <menuitem action='FileCloseAll' />
      <separator />
      <menuitem action='FileQuit' />
    </menu>
    <menu action='EditMenu'>
      <menuitem action='EditUndo' />
      <menuitem action='EditRedo' />
      <separator />
      <menuitem action='EditOpenPreview' />
    </menu>
  </menubar>
</ui>
"""

class Multitoner(Gtk.Grid):
    """ Manage multiple Documents and provide gtk menus and accelarators """
    def __init__(self):
        Gtk.Grid.__init__(self)
        self._gradient_worker, self._preview_worker = gs_workers_factory()
        
        self._documents = {}
        self._active_document = None
        
        self._document_actions = self._make_document_actions()
        self._global_actions = self._make_global_actions()
        self.menubar = menubar = self._init_menu()
        self.attach(menubar, 0, 0, 1, 1)
        self._notebook = Gtk.Notebook()
        self._notebook.set_scrollable(True)
        
        self._notebook.connect('switch-page', self.switch_page_handler)
        self._notebook.connect('page-removed' , self.page_add_remove_handler)
        self._notebook.connect('page-added'   , self.page_add_remove_handler)
        
        self.attach(self._notebook, 0, 1, 1, 1)
        self._set_active_document_state()
        self._set_global_state()
    
    @staticmethod
    def _actions_set_sensitive(action_group, *action_tuples):
        for action_name, sensitive in action_tuples:
            action = action_group.get_action(action_name)
            action.set_sensitive(sensitive)
    
    def _set_active_document_state(self):
        if self._active_document is None:
            # there is no current page
            self._document_actions.set_sensitive(False)
            return
        else:
            self._document_actions.set_sensitive(True)
        
        undos, redos = self._active_document.history.get_counts()
        actions = (
              ('FileSaveDocument', self._active_document.has_changes)
            , ('EditUndo', undos > 0)
            , ('EditRedo', redos > 0)
            , ('FileCloseOther', len(self._documents) > 1)
            
        )
        self._actions_set_sensitive(self._document_actions, *actions)
    
    def _get_document_by_widget(self, widget):
        for doc in self._documents.values():
            if doc.widget is widget:
                return doc
        return None
    
    def _get_document_by_page(self, page):
        widget = self._notebook.get_nth_page(page)
        return self._get_document_by_widget(widget)
    
    def _set_global_state(self):
        actions = (
              ('FileSaveAll', self._has_changed_documents)
            , ('FileCloseAll', len(self._documents) > 0)
        )
        self._actions_set_sensitive(self._global_actions, *actions)
    
    def _set_current_page(self, page=None):
        if page is None:
            page = self._notebook.get_current_page()
        # _active_document is either a Document or None
        self._active_document = self._get_document_by_page(page)
        self._set_active_document_state()
        self._set_global_state()
    
    def switch_page_handler(self, widget, page, page_num):
        self._set_current_page(page_num)
    
    def page_add_remove_handler(self, *data):
        self._set_current_page()
    
    def _get_document_by_filename(self, filename):
        for doc in self._documents.values():
            if doc.filename == filename:
                return doc
        return None
    
    @property
    def _has_changed_documents(self):
        for doc in self._documents.values():
            if doc.has_changes:
                return True
        return False
    
    def _set_active_page(self, doc):
        page = self._notebook.page_num(doc.widget)
        self._notebook.set_current_page(page)
    
    def on_document_state_update(self, doc, *args):
        if doc is self._active_document:
            self._set_active_document_state()
        self._set_global_state()
    
    def _init_menu(self):
        uimanager = Gtk.UIManager()
        uimanager.add_ui_from_string(UI_INFO)
        uimanager.insert_action_group(self._global_actions)
        uimanager.insert_action_group(self._document_actions)
        menubar = uimanager.get_widget("/MenuBar")
        
        #toolbar = uimanager.get_widget("/ToolBar")
        # this removes the immediate dependency to window
        def onRealize(widget, *args):
            """ 
            closure to connect to window when it establishes this widget
            """
            window = widget.get_toplevel()
            # Add the accelerator group to the toplevel window
            accelgroup = uimanager.get_accel_group()
            window.add_accel_group(accelgroup)
            # connect just once ever
            widget.disconnect(realize_handler_id)
        #save realize_handler_id for the closure of onRealize 
        realize_handler_id = self.connect('realize' , onRealize)
        return menubar
    
    def _make_global_actions(self):
        action_group = ActionGroup('global_actions')
        action_group.add_actions([
              ('FileMenu', None, _('File'), None,
               None, None)
            , ('EditMenu', None, _('Edit'), None,
               None, None)
            , ('FileNew', Gtk.STOCK_NEW, _('New'), '<Ctrl>n',
               _('Start a new document.'), self.action_file_new_handler)
            , ('FileQuit', Gtk.STOCK_QUIT, _('Quit'), '<ctrl>q',
               None, self.action_file_quit_handler)
            , ('FileOpen', Gtk.STOCK_OPEN, _('Open'), '<Ctrl>o',
               _('Open a document.'), self.action_file_open_handler)
            , ('FileSaveAll', Gtk.STOCK_SAVE, _('Save All'), '<Ctrl><Shift>s',
               _('Save all documents.'), self.action_file_save_all_handler)
            , ('FileCloseAll', Gtk.STOCK_CLOSE, _('Close All'), '<Ctrl><Shift>w',
               _('Close all documents.'), self.action_file_close_all_handler)
            ])
        # recent files chooser
        # does only .mtt files
        recent_action = Gtk.RecentAction.new_for_manager('FileOpenRecent',
            _('Recent Files'), None, None, None)
        recent_filter= Gtk.RecentFilter()
        recent_filter.add_pattern ("*" + Document.file_extension);
        recent_action.add_filter(recent_filter)
        recent_action.connect('item-activated', self.open_recent_handler)
        action_group.add_action(recent_action)
        return action_group
    
    def _make_document_actions(self):
        action_group = ActionGroup('document_actions')
        action_group.add_actions([
              ('EditUndo', Gtk.STOCK_UNDO, _('Undo'),  '<Ctrl>z',
               None, self.action_edit_undo_handler)
            , ('EditRedo', Gtk.STOCK_REDO, _('Redo'), '<Ctrl>y',
               None, self.action_edit_redo_handler)
            , ('FileSaveDocument', Gtk.STOCK_SAVE, _('Save'), '<ctrl>s',
               None, self.action_file_save_document_handler)
            , ('FileSaveAsDocument', Gtk.STOCK_SAVE, _('Save As'), '<ctrl><alt>s',
               None, self.action_file_save_document_as_handler)
            , ('FileClose', Gtk.STOCK_CLOSE, _('Close'), '<ctrl>w',
               None, self.action_file_close_handler)
            , ('FileCloseOther', Gtk.STOCK_CLOSE, _('Close Other Documents'), '<ctrl><alt>w',
               None, self.action_file_close_other_handler)
            , ('EditOpenPreview', Gtk.STOCK_PRINT_PREVIEW, _('Open a Preview Window'), None,
               None, self.action_open_preview_handler)
            ])
        
        action_group.add_icon_actions([
              ('FileExportImage', _('Export Image'), _('Export Image as EPS file'),
               'document-save', self.action_file_export_image_handler, '<ctrl>E')
            # , ...
            ])
        action_group.set_sensitive(False)
        return action_group
    
    def _register_document(self, doc):
        self._documents[doc.id] = doc
        doc.label.connect('close', self.close_document_handler, doc.id)
        doc.add(self)
        page = self._notebook.append_page(doc.widget, doc.label)
        self._notebook.set_tab_reorderable(doc.widget, True)
        doc.widget.show_all()
        self._notebook.set_current_page(page)
        return doc.id
    
    def _unregister_document(self, doc):
        doc.remove(self)
        del self._documents[doc.id]
        page = self._notebook.page_num(doc.widget)
        self._notebook.remove_page(page)
    
    def _make_new_document(self):
        doc = Document(self._gradient_worker, self._preview_worker)
        self._register_document(doc)

    def _announce_error(self, error, moreInfo=None):
        window = self.get_toplevel()
        show_message(window, 'error', error, moreInfo)
    
    def _open_document(self, filename):
        try:
            doc = Document.new_from_file(self._gradient_worker, self._preview_worker, filename)
        except Exception as e:
            error = _('Error opening the file "{0}"').format(filename)
            detail = _('Message: {0} {1}').format( e, type(e))
            self._announce_error(error, detail)
        else:
            self._register_document(doc)
    
    def open_document(self, filename):
        doc = self._get_document_by_filename(filename)
        if doc:
            page = self._notebook.page_num(doc.widget)
            self._notebook.set_current_page(page)
            return doc.id
        else:
            return self._open_document(filename)
    
    def _show_file_open_dialog(self):
        window = self.get_toplevel()
        dialog = Gtk.FileChooserDialog(title=_('Open File')
            , parent=window
            , action=Gtk.FileChooserAction.OPEN
            , buttons=( Gtk.STOCK_CANCEL
                      , Gtk.ResponseType.CANCEL
                      , Gtk.STOCK_OPEN
                      , Gtk.ResponseType.ACCEPT
            
            )
        )
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            filename = dialog.get_filename()
            self.open_document(filename)
        dialog.destroy()
    
    def _show_file_save_as_dialog(self, doc):
        self._set_active_page(doc)
        window = self.get_toplevel()
        filename = show_save_as_dialog(window, doc.filename,
                                       Document.untitled_name + Document.file_extension)
        if filename is not None:
            doc.save_as(filename)
    
    def _ask_ok_cancel(self, question, more_info=None):
        window = self.get_toplevel()
        dialog = Gtk.MessageDialog(window, 0, Gtk.MessageType.QUESTION,
                                   Gtk.ButtonsType.OK_CANCEL, question)
        if more_info is not None:
            dialog.format_secondary_text(more_info)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            return True
        return False
    
    def close_document(self, doc):
        ok = True
        if doc.has_changes:
            self._set_active_page(doc)
            ok = self._ask_ok_cancel(
                _('Close without Saving?'),
                _('All changes to the document will be lost.')
            )
        
        if not ok:
            return
        
        self._unregister_document(doc)
        doc.destroy()
    
    def save_document(self, doc):
        if doc.filename is None:
            self._show_file_save_as_dialog(doc)
        else:
            doc.save()
    
    def open_recent_handler(self, widget):
        item = widget.get_current_item()
        uri = item.get_uri()
        if uri.startswith('file://'):
            filename = uri[(len('file://')):]
            self.open_document(filename)
    
    # global action handlers
    def action_file_new_handler(self, widget):
        self._make_new_document()
    
    def action_file_open_handler(self, widget):
        self._show_file_open_dialog()
    
    def close_document_handler(self, widget, id, *data):
        doc = self._documents.get(id, None)
        if doc is None:
            return
        self.close_document(doc)
    
    def quit(self):
        ok = True
        if self._has_changed_documents:
            ok = self._ask_ok_cancel(
                _('Quit without Saving?'),
                _('There are documents with changes. All changes '
                  'will be lost.')
            )
        if ok:
            Gtk.main_quit()
            return False
        return True
    
    def quit_handler(self, *data):
        return self.quit()
    
    action_file_quit_handler = quit_handler
    
    def action_file_close_all_handler(self, widget):
        active = self._active_document
        for doc in self._documents.values():
            self.close_document(doc)
        if active is not None:
            self._set_active_page(active)
        
    def action_file_save_all_handler(self, widget):
        active = self._active_document
        for doc in self._documents.values():
            if doc.has_changes:
                self.save_document(doc)
        if active is not None:
            self._set_active_page(active)

    # document action handlers
    def action_file_close_handler(self, widget):
        if self._active_document is None:
            return
        self.close_document(self._active_document)
    
    def action_file_close_other_handler(self, widget):
        if self._active_document is None:
            return
        active = self._active_document
        for doc in self._documents.values():
            if doc is not active:
                self.close_document(doc)
        self._set_active_page(active)
    
    def action_file_save_document_handler(self, widget):
        if self._active_document is None:
            return
        self.save_document(self._active_document)
    
    def action_file_save_document_as_handler(self, widget):
        if self._active_document is None:
            return
        self._show_file_save_as_dialog(self._active_document)
    
    def action_edit_undo_handler(self, widget):
        if self._active_document is None:
            return
        self._active_document.history.undo()
    
    def action_edit_redo_handler(self, widget):
        if self._active_document is None:
            return
        self._active_document.history.redo()
    
    def action_open_preview_handler(self, widget):
        if self._active_document is None:
            return
        self._active_document.open_preview()
    
    def action_file_export_image_handler(self, widget):
        if self._active_document is None:
            return
        window = self.get_toplevel()
        
        image_filename = show_open_image_dialog(window)
        if image_filename is None:
            return
        
        eps_filename = show_save_as_eps_dialog(window, image_filename)
        if eps_filename is None:
            return
        
        result, message = model2eps(self._active_document.model, image_filename, eps_filename)
        if message:
            window = self.get_toplevel()
            show_message(window, *message)
    
if __name__ == '__main__':
    """ bootstrap the application """
    import sys
    import os
    from gi.repository import GObject
    
    GObject.threads_init()
    use_gui, __ = Gtk.init_check(sys.argv)
    
    window = Gtk.Window()
    window.set_title(_('Multitoner Tool'))
    window.set_default_size(640, 480)
    window.set_has_resize_grip(True)
    # the theme should do so
    window.set_border_width(5)
    
    css_provider = Gtk.CssProvider()
    
    directory = os.path.dirname(os.path.realpath(__file__))
    css_provider.load_from_path(os.path.join(directory, 'style.css'))
    
    screen = window.get_screen()
    style_context = Gtk.StyleContext()
    style_context.add_provider_for_screen(screen, css_provider,
        Gtk.STYLE_PROVIDER_PRIORITY_USER)
    
    multitoner = Multitoner()
    window.connect('delete-event', multitoner.quit_handler)
    
    window.add(multitoner)
    window.show_all()
    Gtk.main()
