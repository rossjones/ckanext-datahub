import fcntl
from itertools import izip_longest
import logging
import math
import os
import pprint
import string
import struct
import sys
import termios

import ckan.lib.cli
import ckan.logic as logic
import ckan.model as model

_logger = logging.getLogger()


class DatahubCommand(ckan.lib.cli.CkanCommand):
    '''Management of the datahub

    Usage:

      paster datahub list-paying-users [<payment-plan>, .. ] -c <config>
        - List users on have a payment plan, grouped by payment plan.
          If one or more payment plans are listed in the arguments, then
          only users belong to those payment plans are listed.

      paster datahub create-payment-plan <payment-plan> -c <config>
        - Create a new payment plan of the given name.

      paster datahub set-payment-plan <user> <payment-plan> -c <config>
        - Add an existing user to an existing payment plan.

      paster datahub remove-from-payment-plan <user> -c <config>
        - Remove an existing User from their payment plan.
    Where:

      <user>          = a user name
      <payment-plan>  = a payment plan name
      <config>        = path to ckan config (.ini) file

    '''

    summary = __doc__.split('\n')[0]
    usage = __doc__
    max_args = None
    min_args = 1

    def command(self):
        '''
        Parse command line args and call appropriate method.
        '''

        self._load_config()

        user = logic.get_action('get_site_user')(
            {'model': model, 'ignore_auth': True}, {})

        self.context = {
            'user': user['name'],
            'model': model,
            'session': model.Session,
        }

        cmd = self.args[0]

        try:

            if cmd in ['--help', '-h', 'help']:
                self.help()
            elif cmd == 'list-paying-users':
                self.list_paying_users(*self.args[1:])

            elif cmd == 'create-payment-plan':
                if len(self.args) != 2:
                    self._error('Expected <payment-plan> argument')
                self.create_plan(self.args[1])

            elif cmd == 'set-payment-plan':
                if len(self.args) != 3:
                    self._error('Expected <user> <payment-plan> arguments')
                self.set_payment_plan(self.args[1], self.args[2])

            elif cmd == 'remove-from-payment-plan':
                if len(self.args) != 2:
                    self._error('Expected <user> argument')
                self.remove_from_payment_plan(self.args[1])

            else:
                print 'Command %s not recognized.' % cmd
                sys.exit(1)
        except logic.ValidationError, e:
            msg = str(e) if str(e) else pprint.pformat(e.error_dict)
            self._error('Validation Error %s' % msg)

    def create_plan(self, plan):
        '''Create a new payment plan'''
        data_dict = {'name': plan}
        result = logic.get_action('datahub_payment_plan_create')(
            self.context,
            data_dict)
        print 'Created payment plan: %s (%s)' % (
            result['name'],
            result['id'])

    def list_paying_users(self, *plans):
        '''List paying users of the given plans'''

        data_dict = {'names': plans}
        plans = logic.get_action('datahub_payment_plan_list')(
            self.context,
            data_dict)

        if len(plans) == 0:
            print 'There are no payment plans defined.  To define one, run:'
            cmd_to_run = ' '.join(sys.argv)\
                            .replace('list-paying-users',
                                     'create-payment-plan <payment-plan>')
            print '\t' + cmd_to_run
            sys.exit(0)

        titles = [plan['name'] for plan in plans]
        stringss = [sorted([user['name'] for user in plan['users']])
                    for plan in plans]

        self._print_items(titles, stringss)

    def remove_from_payment_plan(self, user):
        '''Removes user from any payment plan they may belong to'''
        data_dict = {
            'user': user,
            'payment_plan': None}

        result = logic.get_action('datahub_user_set_payment_plan')(
            self.context,
            data_dict)

        old_pp = result['old_payment_plan']
        old_pp = old_pp['name'] if old_pp else 'none'

        print '%s removed from %s.' % (user, old_pp)

    def set_payment_plan(self, user, plan):
        '''Add given user to plan'''
        data_dict = {
            'user': user,
            'payment_plan': plan}

        result = logic.get_action('datahub_user_set_payment_plan')(
            self.context,
            data_dict)

        def pp_str(pp):
            return pp['name'] if pp else 'none'
        pp_from = pp_str(result['old_payment_plan'])
        pp_to = pp_str(result['new_payment_plan'])

        print '%s\'s payment plan set from % s to %s' % (user, pp_from, pp_to)

    def _print_items(self, titles, stringss):
        '''Prints a nested list of strings.

        If attached to a terminal, then pretty print with columns, otherwise
        print a list of pairs for easier processing.
        '''

        window_width = self._try_to_get_terminal_width()
        if window_width and os.isatty(sys.stdout.fileno()):

            # Figure out the required column width to fit every string within
            # including a gap between columns.
            column_width = max([9] +  # minimum of 10 chars wide
                               [len(s) for ss in stringss for s in ss])
            column_width += 1  # gap between columns

            for title, strings in zip(titles, stringss):
                print '-' * window_width
                print string.center(title, window_width)
                print '-' * window_width
                self._print_in_columns(
                    window_width,
                    column_width,
                    strings)
                print
        else:
            # Don't pretty print.  Just print pairs.  This means any titles
            # without members won't be printed.  But that's probably the best
            # thing for processing output programatically.
            for title, strings in zip(titles, stringss):
                for s in strings:
                    print '\t'.join([title, s])

    def _try_to_get_terminal_width(self):
        '''Attempt to get terminal's width.

        Returns None if not able to determine the width
        '''
        try:
            height, width = struct.unpack(
                'hh',  # unpack 2 short integers ...
                fcntl.ioctl(sys.stdout.fileno(),
                            termios.TIOCGWINSZ,
                            '....'))  # ... into 4 bytes
            return width
        except:
            return None

    def _print_in_columns(self, window_width, column_width, ss):
        '''Print list of strings in columns'''

        if len(ss) is 0:
            return

        num_cols = max(1, window_width / column_width)
        num_rows = int(math.ceil(float(len(ss)) / num_cols))

        columns = [ss[i:i + num_rows] for i in range(0, len(ss), num_rows)]
        rows = izip_longest(*columns, fillvalue='')

        def expand_cell(cell):
            '''Expand a string to fill the column width'''
            return string.ljust(cell, column_width)

        rows = [map(expand_cell, row) for row in rows]
        row_strings = [''.join(row) for row in rows]
        print '\n'.join(row_strings)

    def _error(self, msg):
        print msg
        sys.exit(1)
