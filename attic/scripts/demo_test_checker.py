"""演示 test_checker CLI：读 raw log → 检查"""
import sys
sys.argv = ['manage.py', 'test_checker', '--input',
    r'media\raw\知识城\oasw001&002.a.pri.zscidc2f1.gzxc-hlw/display_fan.txt',
    '--checker', 'custom',
    '--checker-config', '{"func":"check_fan"}']

from app02.management.commands.test_checker import Command
Command().run_from_argv(sys.argv)