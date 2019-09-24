import json
import argparse
from objects import *
from panos import Panos
import getpass
from pandevice import panorama
from pandevice import objects
from pandevice import policies

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
        self.nat_rules = []
        self.services = []
        self.addresses = []
        self.ids = {}
        self.names = {}

        self.TYPE_SWITCH = {
            "service-tcp": self.parse_service,
            "service-udp": self.parse_service,
            "host": self.parse_address,
            "network": self.parse_address,
            "group": self.parse_group,
            "service-group": self.parse_group,
            "nat-rule": self.parse_natrule,
            "nat-section": self.parse_natsection,
            "CpmiGatewayCluster": self.parse_address,
        }


    def add(self, obj):
        if type(obj) is Group:
            self.groups.append(obj)

        if type(obj) is Address:
            self.addresses.append(obj)

        if type(obj) is Service:
            self.services.append(obj)

        if type(obj) is NatRule:
            self.nat_rules.append(obj)

        # For objects that contain other objects...
        if type(obj) is list:
            for o in obj:
                self.add(o)

            return

        self.ids[obj.get_id()] = obj
        self.names[obj.get_name()] = obj

    def summary(self):
        print("Addresses: {} Groups:{} Services:{} Nat-rules: {}".format(len(self.addresses), len(self.groups), len(self.services), len(self.nat_rules)))

    def resolve_all(self):
        # After parsing, resolve all groups
        for group in self.groups:
            group.resolve_members(self.ids)

    def parse(self, d):
        if 'objects-dictionary' in d:
            d = d['objects-dictionary']

        for item in d:
            k = item['type']
            if k in self.TYPE_SWITCH:
                obj = self.TYPE_SWITCH[k](item)
                self.add(obj)
            else:
                #print("type miss: {}".format(k))
                pass


    def parse_natrule(self, d):

        nr = NatRule(d)
        return nr

    def parse_natsection(self, d):
        natrules = []
        for r in d['rulebase']:
            nr = NatRule(r)
            natrules.append(nr)

        return natrules

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
                print("    {}   {}".format(member.name, member.dump()))

    def dump_names(self):
        print("\n".join(self.names.keys()))

    def dump_natmap(self):
        for addr in self.addresses:
            if addr.get_nat():
                print("{}, {}".format(addr.get_name(), addr.get_nat()))

    def dump(self):
        print("{} Groups".format(len(self.groups)))
        self.dump_groups()

    def set_groups(self, panos, dg=None):
        print("Adding {} address objects".format(len(self.addresses)))
        root = "/config/shared"
        if dg:
            root = "/config/devices/entry[@name='localhost.localdomain']/device-group/entry[@name='{}']/".format(dg)

        self.set_list(panos, root+"address", self.addresses)

        address_groups = []
        for g in self.groups:
            if g.group_type == Address:
                address_groups.append(g)
            elif g.group_type == "Group":
                address_groups.append(g)


        print("Adding {} group objects".format(len(self.groups)))
        self.set_list(panos, root+"address-group", address_groups)

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

    def fix_nat(self, host, user, pw):
        pano = panorama.Panorama(host, user, pw)
        panorama.DeviceGroup.refreshall(pano, add=True)
        for dg in pano.children:

            prerulebase = policies.PreRulebase()
            dg.add(prerulebase)

            natrules = policies.NatRule.refreshall(prerulebase)
            self.fix_nat_rules(dg, natrules)

            securityrules = policies.SecurityRule.refreshall(prerulebase)
            self.fix_security_rules(dg, securityrules)

    def fix_nat_rules(self, dg, nat_rules):
        added = set()

        # Finally fix the dynamic rules as well
        for nr in nat_rules:
            new_addrs = []
            if nr.source_translation_translated_addresses:
                for dst in nr.source_translation_translated_addresses:
                    if dst in self.names:
                        dst_obj = self.names[dst]

                        format_name = "NAT_{}".format(dst_obj.get_name())
                        n = dst_obj.get_nat()
                        # Only fix non-hide nat rules
                        if n:
                            if n != 'Gateway':
                                nat_addr = objects.AddressObject(format_name, dst_obj.get_nat())
                                if format_name not in added:
                                    print("Adding {} {}".format(format_name, dst_obj.get_nat()))
                                    dg.add(nat_addr)
                                    nat_addr.create()
                                new_addrs.append(format_name)

                if len(new_addrs) > 0:
                    nr.source_translation_translated_addresses = new_addrs
                    print("Changing DIPP translated addresses in {} to {}".format(nr.name, new_addrs))
                    nr.apply()
        # First we sort out the static source rules

        for nr in nat_rules:
            translated_src = nr.source_translation_static_translated_address
            if translated_src:
                if translated_src in self.names:
                    obj = self.names[translated_src]
                    n = obj.get_nat()
                    # Only fix non-hide nat rules
                    if n:
                        if n != 'Gateway':
                            format_name = "NAT_{}".format(obj.get_name())
                            nat_addr = objects.AddressObject(format_name, obj.get_nat())
                            print("Adding {} {}".format(format_name, obj.get_nat()))
                            dg.add(nat_addr)
                            nat_addr.create()
                            added.add(format_name)

                            nr.source_translation_static_translated_address = format_name
                            print("Fixing source NAT in {} ({})".format(nr.name, format_name))

                            nr.apply()

        # Now fix the incorrect destinations in the policy
        for nr in nat_rules:
            new_addrs = []
            for dst in nr.destination:
                if dst in self.names:
                    dst_obj = self.names[dst]

                    format_name = "NAT_{}".format(dst_obj.get_name())
                    n = dst_obj.get_nat()
                    # Only fix non-hide nat rules
                    if n:
                        if n != 'Gateway':
                            nat_addr = objects.AddressObject(format_name, dst_obj.get_nat())
                            if format_name not in added:
                                print("Adding {} {}".format(format_name, dst_obj.get_nat()))
                                dg.add(nat_addr)
                                nat_addr.create()
                            new_addrs.append(format_name)

            if len(new_addrs) > 0:
                nr.destination = new_addrs
                print("Changing destination addresses in {} to {}".format(nr.name, new_addrs))
                nr.apply()


    def fix_security_rules(self, dg, security_rules):
        requires_fix = {}
        for sr in security_rules:
            match = False

            # Logic here: Assume that rules with source "any" are internet sourced rules.
            if "any" in sr.source:
                for dst in sr.destination:
                    if dst in self.names:
                        dst_obj = self.names[dst]
                        if dst_obj.get_nat():
                            match = True


            if match:
                requires_fix[sr.name] = sr


        for name, sr in requires_fix.items():
            print(name)
            new_addrs = []
            for dst in sr.destination:
                dst_obj = self.names[dst]

                format_name = "NAT_{}".format(dst_obj.get_name())
                n = dst_obj.get_nat()
                # Only fix non-hide nat rules
                if n:
                    if n != 'Gateway':
                        nat_addr = objects.AddressObject(format_name, dst_obj.get_nat())
                        print("Adding {} {}".format(format_name, dst_obj.get_nat()))
                        dg.add(nat_addr)
                        nat_addr.create()
                        new_addrs.append(format_name)
                else:
                    new_addrs.append(dst)

            sr.destination = new_addrs
            print("Changing destination addresses in {} to {}".format(sr.name, new_addrs))
            sr.apply()


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
    h = """
    Converts Checkpoint configuration exports.
    If no arguments are provided, will add all the addressgroups and address objects required into the configuration.
    """
    parser = argparse.ArgumentParser(description=h, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    script_options = parser.add_argument_group("Script options")
    script_options.add_argument("object_files", help="Json filename", nargs="*")
    script_options.add_argument("--group_ranges", help='Output of mgmt_cli show groups show-as-ranges "true" --format json')
    script_options.add_argument("--dump", action="store_true")
    script_options.add_argument("--dump_nat", action="store_true")
    script_options.add_argument("--fix_nat", action="store_true", help="Fixes the security/NAT rulebases to match with autogenerated checkpoint rules.")
    script_options.add_argument("--parseonly", action="store_true")
    script_options.add_argument("--devicegroup", default=None, help="If specified, adds objects to DG instead of shared")

    script_options.add_argument("--username", help="Firewall/Panorama username. Can also use envvar CC_USERNAME.")
    script_options.add_argument("--address", help="Firewall/Panorama address. Can also use envvar CC_ADDRESS")
    script_options.add_argument("--password", help="Firewall/Panorama login password. Can also use envvar CC_PASSWORD")
    args = parser.parse_args()

    parser = Parser()
    for object_file in args.object_files:
        j = parser.parse_file(object_file)
        parser.parse(j)

    parser.resolve_all()
    parser.summary()

    if args.group_ranges:
        j = parser.parse_file(args.group_ranges)
        parser.parse_group_range(j)


    if args.dump_nat:
        parser.dump_natmap()
        exit()

    if args.parseonly:
        exit()


    if args.dump:
        parser.dump()
        exit()


    addr = env_or_prompt("address", args, prompt_long="address or address:port of PANOS Device to configure: ")
    user = env_or_prompt("username", args)
    pw = env_or_prompt("password", args, secret=True)

    if args.fix_nat:
        parser.fix_nat(addr, user, pw)
        exit()
    p = Panos(user=user, addr=addr, pw=pw)
    parser.set_groups(p, args.devicegroup)

if __name__ == '__main__':
    main()

