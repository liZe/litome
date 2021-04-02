#!/usr/bin/env python

"""
Litome
======

:copyright: (c) 2015-2021 by Guillaume Ayoub and contributors.
:license: BSD, see LICENSE for more details.

"""

import os
import sys
from configparser import ConfigParser

from dbus import Bus
from dbus.mainloop.glib import DBusGMainLoop
from gi import require_version
from gi.repository import GLib
from mpd import MPDClient

require_version('Gtk', '3.0')
from gi.repository import Gtk  # noqa


def song_label(song):
    title = song.get('title')
    if isinstance(title, str):
        artist = song.get('artist')
        if artist:
            return '%s – %s' % (artist, title)
        return title
    name = song.get('name')
    if isinstance(name, str):
        return name
    filename = song.get('file')
    if isinstance(filename, str):
        return filename.split('/')[-1].rsplit('.', 1)[0]
    return '?'


class Litome(Gtk.Application):
    def do_activate(self):
        config = ConfigParser()
        config.read(os.path.expanduser('~/.config/litome'))

        self.client = MPDClient()
        for milliseconds in range(100, 5100, 1000):
            self.client.timeout = milliseconds / 1000
            for section in config.sections():
                host = config.get(section, 'host')
                port = config.getint(section, 'port', fallback=6600)
                password = config.get(section, 'password', fallback=None)
                try:
                    self.client.connect(host, port)
                except BaseException:
                    continue
                else:
                    if password:
                        self.client.password(password)
                    self.client.timeout = config.getint(
                        section, 'timeout', fallback=self.client.timeout * 10)
                    break
            else:
                continue
            break

        DBusGMainLoop(set_as_default=True)
        self.bus = Bus(Bus.TYPE_SESSION)
        self.bus_object = self.bus.get_object(
            'org.gnome.SettingsDaemon.MediaKeys',
            '/org/gnome/SettingsDaemon/MediaKeys')
        self.bus_object.GrabMediaPlayerKeys(
            'Litome', 0, dbus_interface='org.gnome.SettingsDaemon.MediaKeys')
        self.bus_object.connect_to_signal(
            'MediaPlayerKeyPressed', self.media_key)

        self.window = Gtk.ApplicationWindow(application=self)
        self.window.set_title('Litome')
        self.window.set_icon_name('audio-x-generic')
        self.window.connect('destroy', lambda window: sys.exit())

        self.header = Gtk.HeaderBar()
        self.header.set_title('Litome')
        self.header.set_show_close_button(True)
        self.window.set_titlebar(self.header)

        self.play_button = Gtk.Button()
        self.play_button.add(
            Gtk.Image.new_from_icon_name('media-playback-start-symbolic', 1))
        self.play_button.connect('clicked', lambda button: self.play())
        self.header.pack_start(self.play_button)

        self.pause_button = Gtk.Button()
        self.pause_button.add(
            Gtk.Image.new_from_icon_name('media-playback-pause-symbolic', 1))
        self.pause_button.connect('clicked', lambda button: self.pause())
        self.header.pack_start(self.pause_button)

        self.volume_button = Gtk.VolumeButton()
        self.volume_button.use_symbolic = True
        self.volume_connection = self.volume_button.connect(
            'value-changed', lambda button, value: self.set_volume(value))
        self.header.pack_start(self.volume_button)

        self.add_button = Gtk.ToggleButton()
        self.add_button.add(
            Gtk.Image.new_from_icon_name('list-add-symbolic', 1))
        self.header.pack_end(self.add_button)

        self.search_entry = Gtk.Entry()
        self.search_entry.connect(
            'activate', lambda entry: self.search(entry.get_text()))

        self.search_store = Gtk.ListStore(str, str, str)

        self.search_menu = Gtk.Popover()
        self.search_menu.set_relative_to(self.add_button)
        self.search_menu.set_modal(False)
        self.add_button.connect(
            'toggled', lambda button:
                self.search_menu.show_all() if button.get_active()
                else self.search_menu.hide())
        self.search_vbox = Gtk.VBox()
        self.search_vbox.add(self.search_entry)
        self.search_menu.add(self.search_vbox)

        self.list_view = Gtk.TreeView()
        self.list_store = Gtk.ListStore(str, str, str)
        self.list_view.set_model(self.list_store)
        self.list_view.set_headers_visible(False)
        self.list_view.connect(
            'row-activated', lambda treeview, path, view: self.play_song(path))
        self.list_view.connect(
            'key-release-event', lambda treeview, event:
                self.remove_song(treeview.get_cursor()[0])
                if event.keyval == 65535 else None)

        playing_column = Gtk.TreeViewColumn('')
        playing_cell = Gtk.CellRendererPixbuf()
        playing_column.pack_start(playing_cell, True)
        playing_column.add_attribute(playing_cell, 'icon-name', 1)
        self.list_view.append_column(playing_column)

        song_column = Gtk.TreeViewColumn('Song')
        song_cell = Gtk.CellRendererText()
        song_column.pack_start(song_cell, True)
        song_column.add_attribute(song_cell, 'text', 2)
        song_column.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
        self.list_view.append_column(song_column)

        scroll = Gtk.ScrolledWindow()
        scroll.add(self.list_view)
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.window.add(scroll)

        self.window.maximize()
        self.window.show_all()
        self.update()
        self.client.send_idle()
        GLib.io_add_watch(self.client, GLib.IO_IN, self.update_idle)

    def search(self, string):
        self.search_store.clear()

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        search_view = Gtk.TreeView()
        search_view.set_model(self.search_store)
        search_view.set_headers_visible(False)
        search_view.connect(
            'row-activated', lambda treeview, path, view: self.add_songs(path))

        type_column = Gtk.TreeViewColumn('')
        type_cell = Gtk.CellRendererPixbuf()
        type_column.pack_start(type_cell, True)
        type_column.add_attribute(type_cell, 'icon-name', 0)
        search_view.append_column(type_column)

        label_column = Gtk.TreeViewColumn('Label')
        label_cell = Gtk.CellRendererText()
        label_column.pack_start(label_cell, True)
        label_column.add_attribute(label_cell, 'text', 1)
        search_view.append_column(label_column)

        self.client.noidle()
        artists_songs = self.client.search('artist', string)
        album_songs = self.client.search('album', string)
        title_songs = self.client.search('title', string)
        file_songs = self.client.search('file', string)

        artists = {}
        for song in artists_songs:
            song_artist = song.get('artist', '?')
            if song_artist in artists:
                if song not in artists[song_artist]:
                    artists[song_artist].append(song)
            else:
                artists[song_artist] = [song]

        albums = {}
        for song in album_songs + artists_songs:
            song_artist = song.get('artist', '?')
            song_album = song.get('album', '?')
            label = '%s – %s' % (song_artist, song_album)
            if label in albums:
                if song not in albums[label]:
                    albums[label].append(song)
            else:
                albums[label] = [song]

        titles = {}
        for song in title_songs + album_songs + artists_songs + file_songs:
            label = song_label(song)
            if label in titles:
                if song not in titles[label]:
                    titles[label].append(song)
            else:
                titles[label] = [song]

        self.client.send_idle()

        for artist, songs in artists.items():
            self.search_store.append(
                ('system-users-symbolic', artist, str(songs)))
        for album, songs in albums.items():
            self.search_store.append(
                ('media-optical-cd-audio-symbolic', album, str(songs)))
        for title, songs in titles.items():
            self.search_store.append(
                ('emblem-music-symbolic', title, str(songs)))

        vbox_children = self.search_vbox.get_children()
        if len(vbox_children) == 2:
            self.search_vbox.remove(vbox_children[1])
        scroll.add(search_view)
        self.search_vbox.add(scroll)
        scroll.show_all()
        search_view.check_resize()
        preferred_size = search_view.get_preferred_size()[1]
        preferred_size = preferred_size.width, preferred_size.height
        max_size = [size / 2 for size in self.window.get_size()]
        size = [min(size) for size in zip(preferred_size, max_size)]
        scroll.set_size_request(*[s + 20 for s in size])

    def add_songs(self, path):
        self.client.noidle()
        for song in eval(self.search_store[path][2]):
            self.client.add(song['file'])
        self.client.send_idle()

    def remove_song(self, path):
        self.client.noidle()
        self.client.deleteid(self.list_store[path][0])
        del self.list_store[path]
        self.list_view.set_cursor(path)
        self.client.send_idle()

    def play_or_pause(self):
        self.client.noidle()
        self.client.pause(int(self.client.status()['state'] == 'play'))
        self.client.send_idle()

    def play(self):
        self.client.noidle()
        self.client.pause(0)
        self.client.send_idle()

    def pause(self):
        self.client.noidle()
        self.client.pause(1)
        self.client.send_idle()

    def play_song(self, path):
        self.client.noidle()
        self.client.playid(self.list_store[path][0])
        self.client.send_idle()

    def set_volume(self, volume):
        self.client.noidle()
        self.client.setvol(int(volume * 100))
        self.client.send_idle()

    def update(self, events=None):
        current_song = self.client.currentsong()
        status = self.client.status()
        state = status['state']

        if events is None or 'playlist' in events:
            current_cursor = self.list_view.get_cursor()[0]
            playlist = self.client.playlistinfo()
            self.list_store.clear()
            for song in playlist:
                self.list_store.append((song['id'], '', song_label(song),))
            if current_cursor is not None:
                self.list_view.set_cursor(current_cursor)

        if events is None or 'playlist' in events or 'player' in events:
            if state == 'play':
                self.header.set_subtitle(song_label(current_song))
                self.play_button.hide()
                self.pause_button.show()
                playing_string = 'media-playback-start-symbolic'
            else:
                self.header.set_subtitle(None)
                self.pause_button.hide()
                self.play_button.show()
                playing_string = 'media-playback-pause-symbolic'

            for row in self.list_store:
                if current_song and row[0] == current_song['id']:
                    row[1] = playing_string
                else:
                    row[1] = ''

        if events is None or 'mixer' in events:
            self.volume_button.handler_block(self.volume_connection)
            self.volume_button.set_value(int(status['volume']) / 100)
            self.volume_button.handler_unblock(self.volume_connection)

    def update_idle(self, source, condition):
        self.update(self.client.fetch_idle())
        self.client.send_idle()
        return True

    def media_key(self, application, *keys):
        for key in keys:
            if key == 'Play':
                self.play_or_pause()
            elif key == 'Stop':
                self.pause()


if __name__ == '__main__':
    Litome().run(sys.argv)
