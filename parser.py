import json
import argparse
from objects import *
from panos import Panos
import getpass

def set_at_path(panos, xpath, elementvalue):
    """
    Runs a "set" action against a given xpath.
    :param panos: .panos object
    :param xpath: xpath to set at
    :param elementvalue: Element value to set
    :return: GET Response page
    """
    params = {
        "type": "config",
        "action": "set",
        "xpath": xpath,
        "element": elementvalue,
    }
    r = panos.send(params)
    print(r.content)
    return r

class Parser:
    def __init__(self):
        self.groups = []
        self.services = []
        self.addresses = []
        self.ids = {}
        self.names = {}

        self.TYPE_SWITCH = {
            "port": self.parse_service,
            "ipv4-address": self.parse_address,
            "subnet4": self.parse_address,
            "members": self.parse_group
        }

    def add(self, obj):
        self.ids[obj.get_id()] = obj
        self.names[obj.get_name()] = obj
        if type(obj) is Group:
            self.groups.append(obj)

        if type(obj) is Address:
            self.addresses.append(obj)

        if type(obj) is Service:
            self.services.append(obj)

    def summary(self):
        print("Addresses: {} Groups:{} Services:{}".format(len(self.addresses), len(self.groups), len(self.services)))

    def resolve_all(self):
        # After parsing, resolve all groups
        for group in self.groups:
            group.resolve_members(self.ids)

    def parse(self, d):

        for item in d:
            for k in self.TYPE_SWITCH.keys():
                if k in item:
                    obj = self.TYPE_SWITCH[k](item)
                    self.add(obj)

        self.resolve_all()
        self.summary()

    def parse_group_range(self, d):
        groups = []
        for obj in d['objects']:
            if "ranges" in obj:
                g = Group(obj)
                groups.append(g)
                for addr_obj in g.members:
                    self.addresses.append(addr_obj)

                # if the group by name already exists in the config merge the two
                if g.get_name() in self.names:

                    existing_group = self.names[g.get_name()]
                    existing_group.combine(g.members)
                # If the group by name doesn't already exist add this as a new group
                else:
                    self.groups.append(g)

        return groups

    def parse_service(self, d):
        s = Service(d)
        return s

    def parse_address(self, d):
        a = Address(d)
        return a

    def parse_group(self, d):
        g = Group(d)
        return g

    def parse_file(self, fn):
        s = open(fn).read()
        try:
            r = json.loads(s)
        except json.decoder.JSONDecodeError:
            # wrap in brackets
            s = "["+s+"]"

            r = json.loads(s)

        return r

    def dump_groups(self):
        for g in self.groups:
            print(" {} : {}".format(g.get_name(), g.group_type))
            for member in g.members:
                print("    {}   {}".format(member.name, type(member)))

    def dump_names(self):
        print("\n".join(self.names.keys()))

    def dump(self):
        print("{} Groups".format(len(self.groups)))
        self.dump_groups()

    def set_groups(self, panos):
        print("Adding {} address objects".format(len(self.addresses)))
        self.set_list(panos, "/config/shared/address", self.addresses)

        address_groups = []
        for g in self.groups:
            if g.group_type == Address:
                address_groups.append(g)

        print("Adding {} group objects".format(len(self.groups)))
        self.set_list(panos, "/config/shared/address-group", address_groups)

    def set_list(self, panos, xpath, objects):
        entries = ""
        dedup = {}

        for obj in objects:
            dedup[obj.name] = obj

        for name, obj in dedup.items():
            entries = entries + obj.to_xml()

        print("Adding {} deduped objects".format(len(dedup)))
        set_at_path(panos, xpath, entries)

        return entries



def json_pp(j):
    print(json.dumps(j, indent=4, sort_keys=True))

def env_or_prompt(prompt, args, prompt_long=None, secret=False):
    k = "CC_{}".format(prompt).upper()
    e = os.getenv(k)
    if e:
        return e

    if args.__dict__[prompt]:
        return args.__dict__[prompt]

    if secret:
        e = getpass.getpass(prompt + ": ")
        return e

    if prompt_long:
        e = input(prompt_long)
        return e

    e = input(prompt + ": ")
    return e

def main():
    parser = argparse.ArgumentParser(description="Convert checkpoint json configuration exports", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    script_options = parser.add_argument_group("Script options")
    script_options.add_argument("object_file", help="Json filename")
    script_options.add_argument("--group_ranges", help='Output of mgmt_cli show groups show-as-ranges "true" --format json')
    script_options.add_argument("--dump", action="store_true")
    script_options.add_argument("--dump_name")
    script_options.add_argument("--parseonly", action="store_true")

    script_options.add_argument("--username", help="Firewall/Panorama username. Can also use envvar CC_USERNAME.")
    script_options.add_argument("--address", help="Firewall/Panorama address. Can also use envvar CC_ADDRESS")
    script_options.add_argument("--password", help="Firewall/Panorama login password. Can also use envvar CC_PASSWORD")
    args = parser.parse_args()

    parser = Parser()
    j = parser.parse_file(args.object_file)
    parser.parse(j)

    if args.group_ranges:
        j = parser.parse_file(args.group_ranges)
        parser.parse_group_range(j)


    if args.parseonly:
        exit()


    if args.dump:
        parser.dump()
        exit()


    addr = env_or_prompt("address", args, prompt_long="address or address:port of PANOS Device to configure: ")
    user = env_or_prompt("username", args)
    pw = env_or_prompt("password", args, secret=True)

    p = Panos(user=user, addr=addr, pw=pw)
    parser.set_groups(p)

if __name__ == '__main__':
    main()

