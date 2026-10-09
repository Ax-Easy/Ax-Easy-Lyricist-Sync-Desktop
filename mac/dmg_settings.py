# dmgbuild settings: dmgbuild -s mac/dmg_settings.py -D app="dist/Lyricist Sync.app" \
#     -D background=build/dmg-background.tiff "Lyricist Sync" AxEasy-LyricistSync-1.3.1-mac-universal.dmg
import os.path

application = defines['app']  # noqa: F821
appname = os.path.basename(application)
format = 'UDZO'            # zlib: mountable on every supported macOS
compression_level = 9
filesystem = 'HFS+'
size = None
files = [application]
symlinks = {'Applications': '/Applications'}
badge_icon = None
icon_locations = {appname: (170, 205), 'Applications': (490, 205)}   # = mac/make_dmg_background.py
background = defines.get('background', 'builtin-arrow')  # noqa: F821
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
sidebar_width = 180
window_rect = ((200, 140), (660, 420))
default_view = 'icon-view'
show_icon_preview = False
arrange_by = None
grid_offset = (0, 0)
grid_spacing = 100
scroll_position = (0, 0)
label_pos = 'bottom'
text_size = 13
icon_size = 112
license = None
