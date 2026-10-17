# -*- coding: utf-8 -*-
# Copyright (C) 2026 RosePounce
# SPDX-License-Identifier: GPL-3.0-or-later
"""Application: main loop, states and input handling."""

import os
import random
import sys

import pygame

from . import (bugreport, bugsend, i18n, keymap, lockstep, mapfile, net,
               prefs, paths,screens, sprites)
from .audio import Audio
from .editor import MapEditor
from .fonts import load_fonts
from .game import (ST_DEFEAT, ST_PAUSED, ST_PLAYING, ST_VICTORY, Game)
from .layout import Layout
from .settings import (BUILDINGS, DEFAULT_MAP_SIZE, DIFF_ORDER, FPS,
                       RENDER_HEIGHT_CAP, RESOLUTIONS, SCREEN_H, SCREEN_W,
                       TILE, UNITS, UPGRADES)
from .ui import HUD
from .render import WorldRenderer
from .utils import clamp
from .world import World

S_MENU, S_GAME, S_END, S_LAN, S_OPTIONS, S_KEYS, S_EDITOR = range(7)
DOUBLE_CLICK_MS = 320


class App(object):
    def __init__(self, difficulty=None, seed=None, sound=True, fog=True,
                 fullscreen=False, skip_menu=False, resolution=None,
                 edge_scroll=True, language=None):
        pygame.init()
        # The language first: the window title and the button labels are
        # frozen the moment they are built.
        i18n.set_language(language or i18n.detect())
        pygame.display.set_caption(i18n.t("app.title"))
        # The cat style before the first sprites are warmed, so the caches are
        # built in the look the player picked last time.
        sprites.set_cat_style(prefs.get("classic_cats", False))
        self.clock = pygame.time.Clock()
        self.audio = Audio(sound)

        self.menu = None
        self.game = None
        self.hud = None
        self.renderer = None
        self.screen = None
        self.layout = Layout()
        self.fonts = None
        self.fullscreen = bool(fullscreen)
        self.windowed_size = None
        self.requested_res = tuple(resolution) if resolution else None
        self.apply_display(self.requested_res, self.fullscreen)

        self.menu = screens.MainMenu(self.fonts, self.layout)
        self.menu.fog = fog
        self.menu.sound = sound
        self.menu.fullscreen = self.fullscreen
        self.menu.res_index = (RESOLUTIONS.index(self.requested_res)
                               if self.requested_res in RESOLUTIONS else -1)
        if difficulty in DIFF_ORDER:
            self.menu.diff_index = DIFF_ORDER.index(difficulty)
        self.menu.refresh_maps()
        self.seed = seed
        self.editor = None          # MapEditor while it is open

        self.state = S_MENU
        self.running = True
        self.show_help = False
        self.show_guide = False
        self.paused = False
        self.pause_buttons = []
        self.end_buttons = []

        self.drag_start = None
        self.drag_rect = None
        self.panning = False
        self.last_click = (0, None)

        self.edge_scroll = edge_scroll
        self.menu.edge_scroll = edge_scroll
        self.lan = screens.LanScreen(self.fonts, self.layout)
        self.options = screens.OptionsScreen(self.fonts, self.layout, self.menu)
        self.keys = screens.KeysScreen(self.fonts, self.layout)
        self.host = None            # net.Host while hosting
        self.browser = None         # net.Browser while searching
        self.pending_link = None    # link waiting for the start message
        self.session = None         # lockstep.NetSession over the network
        self.bug_mode = False
        self.bug_text = ""
        self.bug_text_events = False   # does SDL send us TEXTINPUT events?
        self.bug_shot = None
        self.bug_saved = None
        self.bug_attach_shot = True    # the screenshot checkbox, kept between reports
        self.bug_ticket = None         # outbox ticket of the report just saved
        self.bug_send = None           # "sending", then a bugsend outcome
        self.bug_areas = {}            # clickable areas of the report window
        self._bug_prev_paused = False
        # Reports a previous session could not send go out now.
        bugsend.flush_async()

        if skip_menu:
            self.start_game()

    # ------------------------------------------------------------ display ----
    @staticmethod
    def desktop_size():
        """The desktop resolution, for "native" fullscreen."""
        try:
            sizes = pygame.display.get_desktop_sizes()
            if sizes:
                return tuple(sizes[0])
        except Exception:
            pass
        info = pygame.display.Info()
        if info.current_w > 0 and info.current_h > 0:
            return (info.current_w, info.current_h)
        return (SCREEN_W, SCREEN_H)

    def _pick_size(self, resolution, fullscreen):
        desk = self.desktop_size()
        if resolution is not None:
            return tuple(resolution)
        if fullscreen:
            # We cap the render resolution: beyond it SDL scales the image up
            # on the GPU (the SCALED flag), which fills the screen without
            # collapsing the frame rate. --resolution forces native rendering.
            if desk[1] > RENDER_HEIGHT_CAP:
                k = RENDER_HEIGHT_CAP / float(desk[1])
                return (int(round(desk[0] * k / 2) * 2), RENDER_HEIGHT_CAP)
            return desk
        if self.windowed_size:
            return self.windowed_size
        # windowed: the largest listed resolution that fits on the screen
        best = (SCREEN_W, SCREEN_H)
        for (w, h) in RESOLUTIONS:
            if w <= desk[0] * 0.92 and h <= desk[1] * 0.88:
                best = (w, h)
        return best

    def _attempts(self, size, fullscreen):
        """The display modes to try, from the most desirable to the safest.

        `SCALED` lets SDL scale the image up on the GPU to fill the screen;
        some drivers refuse it, hence the fallbacks.
        """
        if fullscreen:
            return ((size, pygame.FULLSCREEN | pygame.SCALED, True),
                    (size, pygame.FULLSCREEN | pygame.SCALED, False),
                    (self.desktop_size(), pygame.FULLSCREEN, False),
                    (size, pygame.RESIZABLE, False))
        return ((size, pygame.RESIZABLE, True),
                (size, pygame.RESIZABLE, False),
                (size, 0, False))

    def apply_display(self, resolution=None, fullscreen=False):
        """(Re)create the window, then retune the whole interface to its size."""
        size = self._pick_size(resolution, fullscreen)
        last = None
        for (sz, flags, vsync) in self._attempts(size, fullscreen):
            try:
                if vsync:
                    self.screen = pygame.display.set_mode(sz, flags, vsync=1)
                else:
                    self.screen = pygame.display.set_mode(sz, flags)
                self.fullscreen = bool(fullscreen and (flags & pygame.FULLSCREEN))
                break
            except pygame.error as exc:
                last = exc
        else:
            raise RuntimeError(i18n.t("cli.no_window", error=last))
        self.refresh_layout()

    def refresh_layout(self):
        """Recompute scales, fonts and sprites for the current size."""
        self.layout = Layout(*self.screen.get_size())
        sprites.set_asset_scale(self.layout.asset_scale)
        self.fonts = load_fonts(self.layout.scale)
        sprites.prewarm()
        if self.menu is not None:
            self.menu.relayout(self.layout, self.fonts)
        if getattr(self, "lan", None) is not None:
            self.lan.relayout(self.layout, self.fonts)
        if getattr(self, "options", None) is not None:
            self.options.relayout(self.layout, self.fonts)
        if getattr(self, "keys", None) is not None:
            self.keys.relayout(self.layout, self.fonts)
        if getattr(self, "editor", None) is not None:
            self.editor.relayout(self.layout, self.fonts)
        if self.game is not None:
            self.game.resize(self.layout)
            self.hud.set_fonts(self.fonts)
            self.hud.relayout()
            self.renderer.invalidate()
            self._make_buttons()

    def apply_language(self, code, remember=True):
        """Switch the language mid-run: the title and labels are rebuilt."""
        applied = i18n.set_language(code)
        if remember:
            i18n.remember(applied)
        pygame.display.set_caption(i18n.t("app.title"))
        self.menu.relayout(self.layout, self.fonts)
        self.lan.relayout(self.layout, self.fonts)
        self.options.relayout(self.layout, self.fonts)
        self.keys.relayout(self.layout, self.fonts)
        if self.editor is not None:
            self.editor.relayout(self.layout, self.fonts)
        if self.game is not None:
            self._make_buttons()
        return applied

    def toggle_fullscreen(self):
        going_full = not self.fullscreen
        self.apply_display(self.requested_res if going_full else None,
                           going_full)
        if self.menu is not None:
            self.menu.fullscreen = self.fullscreen

    def _make_buttons(self):
        u = self.layout.u
        cx = self.layout.w // 2
        bw, bh = u(260), u(50)
        top = self.layout.h // 2 - u(110)
        self.pause_buttons = [
            screens.Button((cx - bw // 2, top, bw, bh),
                           i18n.t("pause.resume"), "resume"),
            screens.Button((cx - bw // 2, top + u(60), bw, bh),
                           i18n.t("pause.restart"), "restart"),
            screens.Button((cx - bw // 2, top + u(120), bw, bh),
                           i18n.t("pause.menu"), "menu"),
            screens.Button((cx - bw // 2, top + u(180), bw, bh),
                           i18n.t("pause.quit"), "quit"),
        ]
        ew, ey = u(200), self.layout.h - u(120)
        self.end_buttons = [
            screens.Button((cx - u(330), ey, ew, bh),
                           i18n.t("end.replay"), "restart"),
            screens.Button((cx - u(100), ey, ew, bh), i18n.t("end.menu"), "menu"),
            screens.Button((cx + u(130), ey, ew, bh), i18n.t("end.quit"), "quit"),
        ]

    # --------------------------------------------------------------- game ----
    def make_world(self, seed=None):
        """The map picked in the menu: a saved one, or one generated from
        `seed` at the chosen size. Also returns the message to show when a
        saved map could not be read and a generated one stands in for it."""
        path, _name, side = self.menu.map_choice()
        if path is not None:
            try:
                return mapfile.load(path), None
            except (OSError, mapfile.MapError) as exc:
                return World(seed, side), i18n.t("messages.map_unreadable",
                                                 error=exc)
        return World(seed, side), None

    def start_game(self):
        self.close_net()
        diff = DIFF_ORDER[self.menu.diff_index]
        self.audio.enabled = self.audio.enabled and self.menu.sound
        world, problem = self.make_world(self.seed)
        self.game = Game(world, difficulty=diff, fog_enabled=self.menu.fog,
                         audio=self.audio if self.menu.sound else None,
                         layout=self.layout)
        self.hud = HUD(self.game, self.fonts)
        self.renderer = WorldRenderer(self.game)
        self.game.camera.edge_scroll = self.edge_scroll
        self.state = S_GAME
        self.paused = False
        self.show_help = False
        self._make_buttons()
        self.game.message(i18n.t("messages.welcome"), (230, 226, 210))
        self.game.message(i18n.t("messages.help_hint"), (200, 210, 230))
        if problem:
            self.game.message(problem, (240, 140, 140))

    # ------------------------------------------------------------- boucle ----
    def run(self):
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            dt = min(dt, 0.05)
            self.handle_events(dt)
            self._poll_bug_sends()
            self.update(dt)
            self.draw()
            pygame.display.flip()
        pygame.quit()

    def update(self, dt):
        if self.bug_mode and self.session is None:
            return          # over the network the game goes on: do not block the other side
        if self.state == S_LAN:
            self.lan.t = getattr(self.lan, "t", 0.0) + dt
            self._update_lan(dt)
            return
        if self.state == S_OPTIONS:
            self.options.update(dt)
            return
        if self.state == S_KEYS:
            self.keys.update(dt)
            return
        if self.state == S_EDITOR:
            self.editor.update(dt)
            return
        if self.state == S_MENU:
            self.menu.update(dt)
        elif self.state == S_GAME:
            if not self.paused and not self.show_help and not self.show_guide:
                g = self.game
                keys = pygame.key.get_pressed()
                focused = pygame.mouse.get_focused()
                if not self.panning:
                    g.camera.update(dt, keys, pygame.mouse.get_pos(), focused)
                else:
                    g.camera.update(dt, keys,
                                (self.layout.w // 2, self.layout.h // 2), False)
                g.update_hover(pygame.mouse.get_pos(), focused)
                if self.session is not None:
                    self.session.update(dt)
                    if self.session.lost or self.session.desync:
                        g.message(self.session.status(), (240, 140, 140))
                else:
                    g.update(dt)
                if g.state in (ST_VICTORY, ST_DEFEAT):
                    self.state = S_END

    def draw(self):
        screen = self.screen
        if self.state == S_EDITOR:
            self.editor.draw(screen)
            if self.show_guide:
                screens.draw_guide(screen, self.fonts, self.layout)
            self._draw_bug_overlay(screen)
            return
        if self.state == S_KEYS:
            self.keys.draw(screen)
            if self.show_guide:
                screens.draw_guide(screen, self.fonts, self.layout)
            elif self.show_help:
                screens.draw_help(screen, self.fonts, self.layout)
            self._draw_bug_overlay(screen)
            return
        if self.state == S_OPTIONS:
            self.options.draw(screen)
            if self.show_guide:
                screens.draw_guide(screen, self.fonts, self.layout)
            elif self.show_help:
                screens.draw_help(screen, self.fonts, self.layout)
            self._draw_bug_overlay(screen)
            return
        if self.state == S_LAN:
            self.lan.draw(screen, self.host, self.browser,
                          getattr(self.lan, "t", 0.0))
            if self.show_guide:
                screens.draw_guide(screen, self.fonts, self.layout)
            elif self.show_help:
                screens.draw_help(screen, self.fonts, self.layout)
            self._draw_bug_overlay(screen)
            return
        if self.state == S_MENU:
            self.menu.draw(screen)
            if self.show_guide:
                screens.draw_guide(screen, self.fonts, self.layout)
            elif self.show_help:
                screens.draw_help(screen, self.fonts, self.layout)
            self._draw_bug_overlay(screen)
            return

        self.renderer.draw(screen, self.fonts[0])
        if self.drag_rect and not self.game.build_mode:
            box = pygame.Surface(self.drag_rect.size, pygame.SRCALPHA)
            box.fill((120, 230, 150, 40))
            pygame.draw.rect(box, (160, 245, 180), box.get_rect(), 2)
            screen.blit(box, self.drag_rect.topleft)
        self.hud.draw(screen, int(self.clock.get_fps()))
        if self.session is not None:
            self._draw_net_status(screen)

        if self.state == S_END:
            screens.draw_end(screen, self.fonts, self.game,
                             self.game.state == ST_VICTORY, self.end_buttons,
                             self.layout)
        elif self.show_guide:
            screens.draw_guide(screen, self.fonts, self.layout)
        elif self.show_help:
            screens.draw_help(screen, self.fonts, self.layout)
        elif self.paused:
            screens.draw_pause(screen, self.fonts, self.pause_buttons,
                               self.layout)
        self._draw_bug_overlay(screen)

    # ------------------------------------------------------------ network ----
    def open_lan(self):
        self.close_net()
        self.lan.mode = screens.LanScreen.MENU
        self.lan.message = ""
        self.state = S_LAN

    def close_net(self):
        """Cleanly close whatever is lying around: host, discovery, session."""
        if self.session is not None:
            self.session.close()
            self.session = None
        if self.host is not None:
            self.host.close()
            self.host = None
        if self.browser is not None:
            self.browser.close()
            self.browser = None
        if self.pending_link is not None:
            self.pending_link.close()
            self.pending_link = None

    def start_hosting(self):
        self.close_net()
        try:
            import socket
            self.host = net.Host(name=i18n.t("lan.host_name",
                                             machine=socket.gethostname()))
        except Exception as exc:
            self.lan.message = i18n.t("lan.port_busy", port=net.PORT, error=exc)
            return
        self.lan.mode = screens.LanScreen.HOSTING
        self.lan.message = ""

    def start_browsing(self):
        self.close_net()
        self.browser = net.Browser()
        self.lan.mode = screens.LanScreen.BROWSING
        self.lan.message = ""

    def join(self, address, port=net.PORT):
        self.lan.message = i18n.t("lan.connecting", address=address)
        try:
            link = net.connect(address, port, timeout=4.0)
        except Exception as exc:
            self.lan.message = i18n.t("lan.cannot_connect", error=exc)
            return
        self.pending_link = link

    def _update_lan(self, dt):
        """Advance the wait: welcoming a player, or the start message arriving."""
        if self.host is not None and self.host.connected:
            link = self.host.link
            self.host.link = None          # the session takes it over
            self.host.close()
            self.host = None
            seed = random.randrange(1 << 30)
            world, _problem = self.make_world(seed)
            start = {"type": "start", "protocole": net.PROTOCOL,
                     "seed": seed, "size": world.w, "fog": self.menu.fog,
                     "team": 1}
            if world.name:              # drawn in the editor: send it whole
                start["map"] = mapfile.to_text(world)
            link.send(start)
            self.start_network_game(link, 0, world, self.menu.fog)
            return
        if self.pending_link is not None:
            if not self.pending_link.alive:
                self.lan.message = i18n.t("lan.link_lost")
                self.pending_link = None
                return
            for msg in self.pending_link.poll():
                if msg.get("type") != "start":
                    continue
                if msg.get("protocole") != net.PROTOCOL:
                    self.lan.message = i18n.t(
                        "lan.version_mismatch", theirs=msg.get("protocole"),
                        ours=net.PROTOCOL)
                    self.pending_link.close()
                    self.pending_link = None
                    return
                link = self.pending_link
                self.pending_link = None
                try:
                    world = self.world_from_start(msg)
                except (mapfile.MapError, TypeError, ValueError) as exc:
                    self.lan.message = i18n.t("lan.bad_map", error=exc)
                    link.close()
                    return
                self.start_network_game(link, int(msg.get("team", 1)),
                                        world, bool(msg.get("fog", True)))
                return

    @staticmethod
    def world_from_start(msg):
        """The host's map, from its start message: carried whole when it
        was drawn in the editor, otherwise grown again from the seed."""
        if msg.get("map"):
            return mapfile.from_text(msg["map"])
        return World(int(msg["seed"]), int(msg.get("size", DEFAULT_MAP_SIZE)))

    def start_network_game(self, link, team, world, fog):
        """Start the shared game: the same map, one side per machine."""
        self.close_net()
        self.seed = world.seed
        self.game = Game(world, difficulty="tomcat", fog_enabled=fog,
                         audio=self.audio if self.menu.sound else None,
                         layout=self.layout, local_team=team, use_ai=False)
        self.hud = HUD(self.game, self.fonts)
        self.renderer = WorldRenderer(self.game)
        self.game.camera.edge_scroll = self.edge_scroll
        self.session = lockstep.NetSession(self.game, link, team)
        self.state = S_GAME
        self.paused = False
        self.show_help = False
        self._make_buttons()
        self.game.message(i18n.t("messages.net_welcome",
                                 player=self.game.human.name), (176, 212, 246))
        self.game.message(i18n.t("messages.net_delay"), (200, 210, 230))

    # ----------------------------------------------------------- bug report --
    def open_bug_report(self):
        if self.bug_mode:
            return
        self.bug_shot = self.screen.copy()      # the screen as it is, without the window
        if self.editor is not None:
            self.editor.stop_name()             # the report takes the keyboard
        self._bug_prev_paused = self.paused
        self.paused = True
        self.bug_mode = True
        self.bug_text = ""
        self.bug_saved = None
        self.bug_ticket = None
        self.bug_send = None
        # SDL sends both KEYDOWN *and* TEXTINPUT for one printable key.
        # Reading both doubled every letter typed. TEXTINPUT is authoritative
        # as soon as it is available: it alone knows how to compose accents
        # and the characters of a non-Latin keyboard.
        self.bug_text_events = False
        try:
            pygame.key.start_text_input()
            self.bug_text_events = hasattr(pygame, "TEXTINPUT")
        except Exception:
            pass

    def close_bug_report(self):
        self.bug_mode = False
        self.bug_shot = None
        self.bug_saved = None
        self.paused = self._bug_prev_paused
        try:
            pygame.key.stop_text_input()
        except Exception:
            pass

    def submit_bug_report(self):
        try:
            shot = self.bug_shot if self.bug_attach_shot else None
            txt, png = bugreport.save(self, self.bug_text, shot,
                                      int(self.clock.get_fps()))
        except Exception as exc:
            self.bug_saved = [i18n.t("bug.save_failed"), str(exc)]
            return
        self.bug_saved = [os.path.basename(txt)]
        if png:
            self.bug_saved.append(os.path.basename(png))
        self.bug_saved.append(i18n.t("bug.in_folder",
                                     folder=os.path.dirname(txt)))
        if self.game is not None:
            self.game.message(i18n.t("messages.bug_saved",
                                     file=os.path.basename(txt)),
                              (168, 220, 168))
        if not bugsend.enabled():
            bugsend.log("%s: not sent, no relay address (BUG_REPORT_URL, "
                        "PURRTAGE_REPORT_URL)" % os.path.basename(txt))
            return
        try:
            self.bug_ticket = bugsend.queue_report(txt, png, self.bug_text)
        except OSError as exc:
            bugsend.log("%s: not sent, outbox unwritable (%s)"
                        % (os.path.basename(txt), exc))
            return                  # saved on disk all the same
        self.bug_send = "sending"
        bugsend.send_async([self.bug_ticket])

    def _poll_bug_sends(self):
        """Pick up what the sending thread has finished."""
        for ticket, outcome in bugsend.results():
            if ticket != self.bug_ticket:
                continue            # an older report, retried at startup
            self.bug_send = outcome
            if outcome == bugsend.SENT and self.game is not None:
                self.game.message(i18n.t("messages.bug_sent"),
                                  (168, 220, 168))

    def _draw_bug_overlay(self, screen):
        if not self.bug_mode:
            return
        caret = int(pygame.time.get_ticks() / 450) % 2 == 0
        self.bug_areas = screens.draw_bug_report(
            screen, self.fonts, self.layout, self.bug_text,
            bugreport.report_dir(), self.bug_saved, caret,
            attach_shot=self.bug_attach_shot, online=bugsend.enabled(),
            status=self.bug_send) or {}

    def _bug_event(self, ev):
        if self.bug_saved is not None:
            if (ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1
                    and "open" in self.bug_areas
                    and self.bug_areas["open"].collidepoint(ev.pos)):
                paths.open_folder(bugreport.report_dir())
            elif ev.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                self.close_bug_report()
            return
        if ev.type == pygame.MOUSEBUTTONDOWN:
            if (ev.button == 1 and "shot" in self.bug_areas
                    and self.bug_areas["shot"].collidepoint(ev.pos)):
                self.bug_attach_shot = not self.bug_attach_shot
            return
        if ev.type == pygame.TEXTINPUT:
            if len(self.bug_text) < bugreport.MAX_DESCRIPTION:
                self.bug_text += ev.text
            return
        if ev.type != pygame.KEYDOWN:
            return
        if ev.key == pygame.K_ESCAPE or ev.key == pygame.K_F8:
            self.close_bug_report()
        elif ev.key == pygame.K_TAB:
            self.bug_attach_shot = not self.bug_attach_shot
        elif ev.key == pygame.K_BACKSPACE:
            self.bug_text = self.bug_text[:-1]
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if ev.mod & pygame.KMOD_SHIFT:
                if len(self.bug_text) < bugreport.MAX_DESCRIPTION:
                    self.bug_text += "\n"
            else:
                self.submit_bug_report()
        elif (not self.bug_text_events
                and ev.unicode and ev.unicode.isprintable()):
            # fallback when the TEXTINPUT event is unavailable
            if len(self.bug_text) < bugreport.MAX_DESCRIPTION:
                self.bug_text += ev.unicode

    def _draw_net_status(self, screen):
        """The network status banner: waiting, desync, cut link."""
        text = self.session.status()
        if not text:
            return
        u = self.layout.u
        img = self.fonts[2].render(text, True, (250, 236, 180))
        box = pygame.Rect(0, 0, img.get_width() + u(28), img.get_height() + u(16))
        box.centerx = self.layout.w // 2
        box.y = self.layout.topbar + u(14)
        panel = pygame.Surface(box.size, pygame.SRCALPHA)
        panel.fill((18, 16, 24, 220))
        screen.blit(panel, box.topleft)
        pygame.draw.rect(screen, (240, 200, 120), box, max(1, u(2)),
                         border_radius=u(6))
        screen.blit(img, (box.centerx - img.get_width() // 2,
                          box.centery - img.get_height() // 2))

    # ------------------------------------------------------------- inputs ----
    def handle_events(self, dt):
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                self.running = False
            elif self.bug_mode:
                self._bug_event(ev)
            elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_F8:
                self.open_bug_report()
            elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_F2:
                self.show_guide = not self.show_guide
                if self.show_guide:
                    self.show_help = False
            elif ev.type == pygame.VIDEORESIZE and not self.fullscreen:
                self.windowed_size = (max(960, ev.w), max(620, ev.h))
                self.requested_res = None
                self.apply_display(self.windowed_size, False)
            elif ev.type == pygame.KEYDOWN and (
                    ev.key == pygame.K_F11
                    or (ev.key == pygame.K_RETURN and ev.mod & pygame.KMOD_ALT)):
                self.toggle_fullscreen()
            elif self.state == S_OPTIONS:
                self._options_event(ev)
            elif self.state == S_KEYS:
                self._keys_event(ev)
            elif self.state == S_EDITOR:
                self._editor_event(ev)
            elif self.state == S_LAN:
                self._lan_event(ev)
            elif self.state == S_MENU:
                self._menu_event(ev)
            elif self.state == S_END:
                self._end_event(ev)
            else:
                self._game_event(ev)

    def _close_overlays(self, ev):
        """Esc or a click closes the help page or the guide. True when handled."""
        if not (self.show_guide or self.show_help):
            return False
        if ev.type == pygame.MOUSEBUTTONDOWN or (
                ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE):
            self.show_guide = False
            self.show_help = False
            return True
        return ev.type == pygame.KEYDOWN

    def _menu_event(self, ev):
        if self._close_overlays(ev):
            return
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_F1:
                self.show_help = True
            elif ev.key == pygame.K_ESCAPE:
                self.running = False
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self.start_game()
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button in (1, 3):
            if self.show_help:
                self.show_help = False
                return
            action = self.menu.click(ev.pos, ev.button)
            if ev.button != 1:
                return
            if action == "play":
                self.start_game()
            elif action == "lan":
                self.open_lan()
            elif action == "options":
                self.state = S_OPTIONS
            elif action == "editor":
                self.open_editor()
            elif action == "help":
                self.show_help = True
            elif action == "quit":
                self.running = False

    def _options_event(self, ev):
        if self._close_overlays(ev):
            return
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            self.state = S_MENU
            return
        if ev.type != pygame.MOUSEBUTTONDOWN or ev.button != 1:
            return
        action = self.options.click(ev.pos)
        if action == "back":
            self.state = S_MENU
        elif action == "keys":
            self.state = S_KEYS
        elif action == "display":
            self.requested_res = self.menu.resolution()
            if self.requested_res is None:
                self.windowed_size = None      # "auto": recompute it
            self.apply_display(self.requested_res, self.menu.fullscreen)
            self.menu.fullscreen = self.fullscreen
        elif action == "edge":
            self.edge_scroll = self.menu.edge_scroll
            if self.game is not None:
                self.game.camera.edge_scroll = self.edge_scroll
            if self.editor is not None:
                self.editor.edge_scroll = self.edge_scroll
                self.editor.camera.edge_scroll = self.edge_scroll
        elif action == "language":
            # The screen already switched the language; remember it and
            # rebuild everything that carries a frozen label.
            self.apply_language(i18n.language())

    def _keys_event(self, ev):
        if self._close_overlays(ev):
            return
        action = None
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            action = self.keys.click(ev.pos)
        elif ev.type == pygame.KEYDOWN:
            # While a row is armed the screen eats every press, Escape apart:
            # otherwise F1 or Escape would fire instead of being captured.
            # Read before the press, which disarms the row: Escape cancelling
            # a capture must not also leave the screen.
            armed = self.keys.waiting is not None
            action = self.keys.key(ev)
            if action is None and ev.key == pygame.K_ESCAPE and not armed:
                action = "back"
        if action == "back":
            self.keys.waiting = None
            self.state = S_OPTIONS
        elif action == "keymap":
            # The action panel prints the key caps: they have to be rebuilt.
            if self.game is not None:
                self.hud.actions = self.hud.build_actions()

    # ---------------------------------------------------------------- editor --
    def open_editor(self):
        """The map editor keeps its map from one visit to the next."""
        if self.editor is None:
            self.editor = MapEditor(self.fonts, self.layout, self.edge_scroll)
        self.state = S_EDITOR

    def _editor_event(self, ev):
        if self.show_guide:
            self._close_overlays(ev)
            return
        if self.editor.event(ev) == "back":
            self.editor.stop_name()
            self.menu.refresh_maps()
            if self.editor.path:
                self.menu.select_map(self.editor.path)
            self.state = S_MENU

    def _lan_event(self, ev):
        if self._close_overlays(ev):
            return
        action = None
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            action = self.lan.click(ev.pos)
        elif ev.type == pygame.KEYDOWN:
            action = self.lan.key(ev)
            if action is None and ev.key == pygame.K_ESCAPE and not self.lan.typing:
                action = "back"
        if action is None:
            return
        if action == "host":
            self.start_hosting()
        elif action == "browse":
            self.start_browsing()
        elif action == "back":
            self.close_net()
            if self.lan.mode != screens.LanScreen.MENU:
                self.lan.mode = screens.LanScreen.MENU
                self.lan.message = ""
            else:
                self.state = S_MENU
        elif action.startswith("connect:"):
            _, address, port = action.split(":")
            self.join(address, int(port))

    def _end_event(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for b in self.end_buttons:
                if b.rect.collidepoint(ev.pos):
                    self._menu_action(b.key)
        elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
            self._menu_action("menu")

    def _menu_action(self, key):
        if key == "resume":
            self.paused = False
        elif key == "restart":
            if self.session is not None:   # no "restart" over the network
                self._menu_action("menu")
                return
            self.seed = None
            self.start_game()
        elif key == "menu":
            self.close_net()
            self.state = S_MENU
            self.game = None
            self.show_help = False
        elif key == "quit":
            self.running = False

    # -------------------------------------------------------- game: inputs ----
    def _game_event(self, ev):
        g = self.game
        if self.show_guide:
            self._close_overlays(ev)
            return
        if ev.type == pygame.KEYDOWN:
            self._key_down(ev)
            return
        if self.paused or self.show_help:
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and self.paused:
                for b in self.pause_buttons:
                    if b.rect.collidepoint(ev.pos):
                        self._menu_action(b.key)
            elif ev.type == pygame.MOUSEBUTTONDOWN and self.show_help:
                self.show_help = False
            return

        if ev.type == pygame.MOUSEBUTTONDOWN:
            self._mouse_down(ev)
        elif ev.type == pygame.MOUSEBUTTONUP:
            self._mouse_up(ev)
        elif ev.type == pygame.MOUSEMOTION:
            self._mouse_motion(ev)
        elif ev.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            if g.view.collidepoint(mx, my):
                g.camera.set_zoom(g.camera.zoom_index + (1 if ev.y > 0 else -1),
                                  (mx, my))

    def _mouse_down(self, ev):
        g = self.game
        pos = ev.pos
        in_view = g.view.collidepoint(pos)

        if ev.button == 2:
            self.panning = True
            self.drag_start = pos
            return

        if self.hud.mini_rect.collidepoint(pos):
            wx, wy = self.hud.mini_to_world(*pos)
            if ev.button == 1:
                g.camera.center_on(wx, wy)
                self.hud.dragging_mini = True
            else:
                g.command(wx, wy, queued=pygame.key.get_mods() & pygame.KMOD_SHIFT)
            return

        if not in_view:
            if ev.button == 1:
                a = self.hud.action_at(pos)
                if a is not None:
                    self.hud.activate(a)
            return

        wx, wy = g.camera.screen_to_world(*pos)
        mods = pygame.key.get_mods()
        shift = bool(mods & pygame.KMOD_SHIFT)

        if ev.button == 1:
            if g.build_mode and BUILDINGS[g.build_mode].get("line"):
                # A rampart is laid on release, along the dragged line. The
                # drag is not a selection box: drop whatever one was pending.
                g.line_start = g._ghost_tile(wx, wy, 1)
                self.drag_start = None
                self.drag_rect = None
                return
            if g.build_mode:
                g.try_place(wx, wy, chain=shift)
                return
            if g.attack_move_mode:
                g.attack_move_mode = False
                g.command(wx, wy, queued=shift, force_attack=True)
                return
            now = pygame.time.get_ticks()
            ent = g.entity_at_point(wx, wy)
            if (now - self.last_click[0] < DOUBLE_CLICK_MS
                    and ent is not None and self.last_click[1] is ent
                    and ent.is_unit and ent.player is g.human):
                g.select_same_type(ent)
                self.last_click = (0, None)
                return
            self.last_click = (now, ent)
            self.drag_start = pos
            self.drag_rect = None
        elif ev.button == 3:
            if g.build_mode:
                g.build_mode = None
                return
            if g.attack_move_mode:
                g.attack_move_mode = False
                return
            g.command(wx, wy, queued=shift)

    def _mouse_motion(self, ev):
        g = self.game
        if self.panning:
            g.camera.pan(ev.rel[0], ev.rel[1])
            return
        if self.hud.dragging_mini and ev.buttons[0]:
            wx, wy = self.hud.mini_to_world(*ev.pos)
            g.camera.center_on(wx, wy)
            return
        if self.drag_start and ev.buttons[0] and not g.build_mode:
            x0, y0 = self.drag_start
            x1, y1 = ev.pos
            rect = pygame.Rect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
            self.drag_rect = rect if rect.w > 5 or rect.h > 5 else None

    def _mouse_up(self, ev):
        g = self.game
        if ev.button == 2:
            self.panning = False
            return
        if ev.button != 1:
            return
        self.hud.dragging_mini = False
        shift = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
        if g.line_start is not None:
            start, g.line_start = g.line_start, None
            self.drag_start = None
            self.drag_rect = None
            if g.build_mode and g.view.collidepoint(ev.pos):
                wx, wy = g.camera.screen_to_world(*ev.pos)
                g.try_place_line(start, wx, wy, chain=shift)
            return
        if self.drag_rect:
            x0, y0 = g.camera.screen_to_world(self.drag_rect.x, self.drag_rect.y)
            x1, y1 = g.camera.screen_to_world(self.drag_rect.right,
                                              self.drag_rect.bottom)
            g.select_box(pygame.Rect(x0, y0, x1 - x0, y1 - y0), shift)
        elif self.drag_start and g.view.collidepoint(ev.pos):
            wx, wy = g.camera.screen_to_world(*ev.pos)
            g.select_single(wx, wy, shift)
        self.drag_start = None
        self.drag_rect = None

    def _key_down(self, ev):
        g = self.game
        k = ev.key
        mods = pygame.key.get_mods()
        ctrl = bool(mods & pygame.KMOD_CTRL)

        if k in (pygame.K_F10, pygame.K_PAUSE):
            if self.session is not None:
                g.message(i18n.t("messages.no_pause_online"), (236, 196, 108))
                return
            self.paused = not self.paused
            if not self.paused:
                g.message(i18n.t("messages.resumed"), (200, 210, 230))
            return
        if k == pygame.K_F7:
            self.edge_scroll = not self.edge_scroll
            g.camera.edge_scroll = self.edge_scroll
            self.menu.edge_scroll = self.edge_scroll
            g.message(i18n.t("messages.edge_scroll",
                             state=i18n.t("messages.on" if self.edge_scroll
                                          else "messages.off")),
                      (200, 210, 230))
            return
        if k == pygame.K_F1:
            self.show_help = not self.show_help
            return
        if k == pygame.K_ESCAPE:
            if self.show_help:
                self.show_help = False
            elif g.build_mode:
                g.build_mode = None
            elif g.attack_move_mode:
                g.attack_move_mode = False
            elif g.selection:
                g.clear_selection()
            else:
                self.paused = not self.paused
            return
        if self.show_help:
            return
        if self.paused:
            return

        if k in (pygame.K_F5, pygame.K_F6) and self.session is not None:
            g.message(i18n.t("messages.speed_shared"), (236, 196, 108))
            return
        if k == pygame.K_F5:
            g.speed = max(0.5, round(g.speed - 0.5, 1))
            g.message(i18n.t("messages.speed", speed="%.1f" % g.speed),
                      (200, 210, 230))
            return
        if k == pygame.K_F6:
            g.speed = min(3.0, round(g.speed + 0.5, 1))
            g.message(i18n.t("messages.speed", speed="%.1f" % g.speed),
                      (200, 210, 230))
            return
        binding = keymap.binding_for(pygame.key.name(k))
        if binding == "command.mute":
            if self.audio:
                self.audio.set_volume(0.0 if self.audio.volume > 0 else 0.55)
                g.message(i18n.t("messages.sound",
                                 state=i18n.t("messages.sound_off"
                                              if self.audio.volume == 0
                                              else "messages.sound_on")),
                          (200, 210, 230))
            return

        if pygame.K_0 <= k <= pygame.K_9:
            n = k - pygame.K_0
            if ctrl:
                g.set_group(n)
            else:
                centre = (self.last_click[0] == -n)
                g.recall_group(n, center=centre)
                self.last_click = (-n, None)
            return

        if k in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
            g.camera.set_zoom(g.camera.zoom_index + 1)
            return
        if k in (pygame.K_MINUS, pygame.K_KP_MINUS):
            g.camera.set_zoom(g.camera.zoom_index - 1)
            return
        if binding == "command.center":
            if g.selection:
                xs = [e.x for e in g.selection]
                ys = [e.y for e in g.selection]
                g.camera.center_on(sum(xs) / len(xs), sum(ys) / len(ys))
            elif g.last_alert_pos:
                g.camera.center_on(*g.last_alert_pos)
            else:
                g.camera.center_on(*g.home_base_pos(g.human))
            return
        if binding == "command.idle_worker":
            g.select_idle_worker()
            return
        if binding == "command.stop":
            g.stop_selection()
            return
        if binding == "command.attack_move":
            if any(u.is_military for u in g.selected_units()):
                g.attack_move_mode = True
                g.build_mode = None
                g.message(i18n.t("messages.attack_move"), (240, 190, 130))
            return
        if k in (pygame.K_DELETE, pygame.K_BACKSPACE):
            a = (self.hud.action_by_hotkey(i18n.t("actions.key_delete"))
                 or self.hud.action_by_hotkey(i18n.t("actions.key_backspace")))
            if a:
                self.hud.activate(a)
            return

        if binding is not None:
            a = self.hud.action_by_binding(binding)
            if a is not None:
                self.hud.activate(a)


def _language_from_argv(argv):
    """Read `--language` before anything else: the parser help is translated."""
    import argparse
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--language", "--langue", dest="language", default=None)
    try:
        known, _rest = pre.parse_known_args(argv)
    except SystemExit:
        return None
    return known.language


def main(argv=None):
    import argparse
    # The language choice decides which language the help is shown in.
    i18n.set_language(_language_from_argv(argv) or i18n.detect())
    languages = i18n.codes()
    parser = argparse.ArgumentParser(description=i18n.t("cli.description"))
    parser.add_argument("--difficulty", "--difficulte", dest="difficulty",
                        choices=DIFF_ORDER, default=None,
                        help=i18n.t("cli.difficulty"))
    parser.add_argument("--language", "--langue", dest="language", default=None,
                        choices=languages, metavar="CODE",
                        help=i18n.t("cli.language", codes=", ".join(languages)))
    parser.add_argument("--seed", type=int, default=None,
                        help=i18n.t("cli.seed"))
    parser.add_argument("--no-sound", "--muet", dest="sound",
                        action="store_false", default=True,
                        help=i18n.t("cli.mute"))
    parser.add_argument("--no-fog", "--sans-brouillard", dest="fog",
                        action="store_false", default=True,
                        help=i18n.t("cli.no_fog"))
    parser.add_argument("--fullscreen", "--plein-ecran", dest="fullscreen",
                        action="store_true", help=i18n.t("cli.fullscreen"))
    parser.add_argument("--resolution", dest="resolution", default=None,
                        metavar="LxH", help=i18n.t("cli.resolution"))
    parser.add_argument("--direct", action="store_true",
                        help=i18n.t("cli.direct"))
    parser.add_argument("--verification", action="store_true",
                        help=i18n.t("cli.check"))
    parser.add_argument("--no-edge-scroll", "--sans-defilement-bord",
                        dest="edge_scroll", action="store_false", default=True,
                        help=i18n.t("cli.no_edge_scroll"))
    args = parser.parse_args(argv)

    resolution = None
    if args.resolution:
        try:
            w, h = args.resolution.lower().replace("*", "x").split("x")
            resolution = (int(w), int(h))
            if min(resolution) < 480:
                raise ValueError
        except ValueError:
            parser.error(i18n.t("cli.bad_resolution",
                                value=repr(args.resolution)))

    try:
        app = App(difficulty=args.difficulty, seed=args.seed, sound=args.sound,
                  fog=args.fog, fullscreen=args.fullscreen,
                  skip_menu=args.direct or args.verification,
                  resolution=resolution, edge_scroll=args.edge_scroll,
                  language=args.language)
    except RuntimeError as exc:
        print("\n%s\n" % exc, file=sys.stderr)
        return 1
    if args.verification:
        return self_check(app)
    app.run()
    return 0


def self_check(app):
    """Check that a built package really works.

    Plays for a few seconds, draws every frame, then saves a screenshot. A
    package that can neither generate its map, nor load its fonts, nor draw,
    fails here instead of failing at the player's place.
    """
    from . import paths
    # A hard-coded message: with no catalog at all there is nothing to
    # translate it with. That is exactly what we want to catch in a package.
    if not i18n.codes():
        print("ÉCHEC : aucun fichier de langue dans %s"
              % ", ".join(i18n.locale_dirs()), file=sys.stderr)
        return 1
    for _ in range(180):
        app.handle_events(1 / 60.0)
        app.update(1 / 60.0)
        app.draw()
    game = app.game
    if game is None or not game.units or not game.buildings:
        print(i18n.t("cli.check_failed"), file=sys.stderr)
        return 1
    folder = paths.ensure("verification")
    capture = os.path.join(folder, "verification.png")
    pygame.image.save(app.screen, capture)
    print(i18n.t("cli.check_ok", layout=app.layout))
    print(i18n.t("cli.check_entities", units=len(game.units),
                 buildings=len(game.buildings),
                 seconds="%.1f s" % game.elapsed))
    print(i18n.t("cli.check_fonts",
                 fonts=[f.get_height() for f in app.fonts]))
    print(i18n.t("cli.check_capture", path=capture))
    print(i18n.t("cli.check_data", path=paths.data_dir()))
    print(i18n.t("cli.check_language", language=i18n.language()))
    # Bug reports travel over HTTPS: a package without certificates would
    # fail every one of them, silently, at the player's place.
    from . import bugsend
    if bugsend.enabled():
        count = bugsend.certificate_count()
        if not count:
            print(i18n.t("cli.check_no_certificates"), file=sys.stderr)
            return 1
        print(i18n.t("cli.check_certificates", count=count,
                     url=bugsend.report_url()))
    return 0
