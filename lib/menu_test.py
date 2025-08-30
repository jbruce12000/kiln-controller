import pytest
from unittest.mock import Mock
from lib.menu import Menu

fake_profiles = [{'profile': 'Bisque'}, {'profile': 'Glaze'}, {'profile': 'GlazeHigh'}, {'profile': 'Earthen'}]


def setup(profile=None):
    oven = Mock()
    oven.profile = profile
    return Menu(fake_profiles, oven)

def test_init():
    m = setup()
    assert m.node == None

def test_click_none_oven_off():
    m = setup()
    m.click()
    assert m.node == m.off

def test_click_none_oven_running():
    m = setup(True)
    m.click()
    assert m.node == m.running

def test_click_menu_back():
    m = setup()
    m.click()
    m.click()
    assert m.node == None

def test_previous_next():
    m = setup()
    m.click()
    m.next()
    assert m.node.index == 1
    m.previous()
    m.click()
    assert m.node == None

def test_start_program():
    m = setup()
    m.click() #menu
    m.next()
    m.click() #profiles
    m.next()
    m.click() #Bisque
    profile = m.node.profile
    m.next()
    m.click() #Start
    assert "Are you sure" in m.node.text
    m.click() #No
    m.click() #Start
    m.next() #Yes
    m.click()
    assert m.node == None #Menu reset
    assert m.oven.profile == profile #Profile started

def test_abort_program():
    m = setup(fake_profiles[0])
    m.click() #Menu
    m.click() #Back
    assert m.node == None
    assert m.oven.profile == fake_profiles[0]
    m.click() #Menu
    m.next()
    m.click() #Abort
    assert "Are you sure" in m.node.text
    m.next() #Yes
    m.click()
    assert m.node == None #Menu reset
    assert m.oven.profile == None #Profile aborted