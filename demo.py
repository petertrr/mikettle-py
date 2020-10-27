#!/usr/bin/env python3
"""Demo file showing how to use the mikettle library."""

import argparse
import re

import sys
import logging

import time

from mikettle.mikettle import MiKettle
from mikettle.mikettle import (
  MI_ACTION,
  MI_MODE,
  MI_SET_TEMPERATURE,
  MI_CURRENT_TEMPERATURE,
  MI_KW_TYPE,
  MI_CURRENT_KW_TIME,
  MI_SET_KW_TIME,
  MI_EWU,
)

def valid_mikettle_mac(mac, pat=re.compile(r"[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}")):
    """Check for valid mac adresses."""
    if not pat.match(mac.upper()):
        raise argparse.ArgumentTypeError('The MAC address "{}" seems to be in the wrong format'.format(mac))
    return mac


def valid_product_id(product_id):
    try:
        product_id = int(product_id)
    except Exception:
        raise argparse.ArgumentTypeError('The Product Id "{}" seems to be in the wrong format'.format(product_id))
    return product_id


def connect(args):
    """Connect to Mi Kettle."""

    logging.basicConfig()
    logging.getLogger().setLevel(logging.DEBUG)

    kettle = MiKettle(args.mac, args.product_id)
    print("Authenticating")
    print("Getting data from mi Kettle")
    print("FW: {}".format(kettle.firmware_version()))
    print("Name: {}".format(kettle.name()))
    print("Manufacturer: {}".format(kettle.manufacturer()))

    kettle.setKW(KWtype=1,temperature=75)
    kettle.setKWTime(time=17)
    kettle.setEWU(mode=0)
    print("Keep warm type: {}".format(kettle.KW()[0]))
    print("Set temperature: {}".format(kettle.KW()[1]))
    print("Set keep warm time: {} hours".format(kettle.KWTime()/2))
    print("Extended warm up: {}".format(kettle.EWU()))

    print("\nRead from status notification:")


    print("Action: {}".format(kettle.parameter_value(MI_ACTION)))
    print("Mode: {}".format(kettle.parameter_value(MI_MODE)))
    print("Set temperature: {}".format(kettle.parameter_value(MI_SET_TEMPERATURE)))
    print("Current temperature: {}".format(kettle.parameter_value(MI_CURRENT_TEMPERATURE)))
    print("Keep warm type: {}".format(kettle.parameter_value(MI_KW_TYPE)))
    print("Current keep warm time: {} minutes".format(kettle.parameter_value(MI_CURRENT_KW_TIME)))
    print("Extended warm up: {}".format(kettle.parameter_value(MI_EWU)))
    print("Set keep warm time: {} hours".format(kettle.parameter_value(MI_SET_KW_TIME)/2))

def main():
    """Main function.

    Mostly parsing the command line arguments.
    """
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(help='sub-command help', )

    parser_poll = subparsers.add_parser('connect', help='connect to mi kettle and receive data')
    parser_poll.add_argument('mac', type=valid_mikettle_mac)
    parser_poll.add_argument('product_id', type=valid_product_id)
    parser_poll.set_defaults(func=connect)

    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == '__main__':
    main()
