import ipaddress
from jinja2 import Template
import os

class Object():
    def __init__(self, id):
        self.id = id
        self.xml_template = ""

    def get_id(self):
        return self.id

    def get_type(self):
        if 'type' in self.__dict__:
            return self.type
        else:
            return "Unknown"

    def to_xml(self):
        t = Template(open("templates" + os.sep + "{}".format(self.xml_template)).read())
        r = t.render(object=self)
        return r

    def get_name(self):
        if 'name' not in self.__dict__:
            return self.id

        if self.name:
            return self.name

        return self.get_id()

    def dump(self):
        return self.get_name()

class Service(Object):
    def __init__(self, v):
        self.__dict__ = v
        self.service_type = v['type']

        super(Service, self).__init__(v['uid'])
        self.xml_template = "service.xml"
        if self.service_type:
            self.service_type = self.service_type.split('-')[1]
        else:
            self.service_type = "tcp"

class NatRule(Object):
    def __init__(self, v):

        self.__dict__ = v
        super(NatRule, self).__init__(v['uid'])

    def dump(self):
        print("\n".join(self.__dict__.keys()))

class Address(Object):
    def __init__(self, v):
        # If this is a subnet mask spec
        if 'subnet4' in v:
            net = ipaddress.IPv4Network('{}/{}'.format(v['subnet4'], v['subnet-mask']))
            cidr = "{}/{}".format(net.network_address, net.prefixlen)
            v['ipv4_address'] = cidr
        # If this is just a regular address
        else:
            v['ipv4_address'] = v['ipv4-address']
            del v['ipv4-address']

        self.__dict__ = v
        super(Address, self).__init__(v['uid'])


        if self.get_type() == "CpmiClusterMember":
            print(self.get_name())

        self.xml_template = "address.xml"

        self.nat_settings = None
        if 'nat-settings' in v:
            self.nat_settings = v['nat-settings']

    def dump(self):
        return self.ipv4_address

class Group(Object):
    def __init__(self, v):
        self.ranges = {}
        self.members = []
        self.__dict__ = v
        super(Group, self).__init__(v['uid'])
        self.xml_template = "address_group.xml"

        self.group_type = "Group"
        if 'ranges' in v:
            self.resolve_ranges()

    def resolve_members(self, objects):
        new_members = []
        for m in self.members:
            if m in objects:
                new_members.append(objects[m])
                gt = type(objects[m])
                # Only set group type wehn we have one object that is not of type group
                if gt is not Group:
                    self.group_type = gt

        if 'others' in self.__dict__:
            print(self.get_name())

        self.members = new_members

    def resolve_ranges(self):
        r = []

        # When there is a special
        if 'others' in self.ranges:
            if len(self.ranges['others']) > 0:
                self.members = []
                return

        self.group_type = Address
        for v4_range in self.ranges['ipv4']:
            start = v4_range['start']
            end = v4_range['end']
            start, end = self.correct_v4address(start, end)
            subnets = list(ipaddress.summarize_address_range(ipaddress.IPv4Address(start), ipaddress.IPv4Address(end)))
            for net in subnets:
                cidr = "{}/{}".format(net.network_address, net.prefixlen)
                name = "RR_{}_{}".format(net.network_address, net.prefixlen)
                address_d = {
                    "uid": "manual",
                    "name": name,
                    "ipv4-address": cidr,
                    "type": "network"
                }
                a = Address(address_d)
                r.append(a)

        self.members = r

    def correct_v4address(self, start, end):
        if start == end:
            return start, end

        octets = str(start).split(".")
        last = octets[3]
        first = octets[:3]

        # correct if range lists the first address as 1
        if int(last) == 1:
            first.append("0")
            newaddr = ".".join(first)
            #print("{}:{} {}".format(start, newaddr, end))
            return newaddr, end

        octets = str(end).split(".")
        last = octets[3]
        first = octets[:3]

        # Correct if range lists the last address as 254
        if int(last) == 254:
            first.append("255")
            newaddr = ".".join(first)
            #print("{} {}:{}".format(start, end, newaddr))
            return start, newaddr

        return start, end

    def to_xml(self):
        if len(self.members) == 0:
            return ""
        t = Template(open("templates" + os.sep + "{}".format(self.xml_template)).read())
        r = t.render(object=self)
        return r

    def combine(self, members):
        for m in members:
            gt = type(m)
            # Only set group type wehn we have one object that is not of type group
            if gt is not Group:
                self.group_type = gt

        self.members = self.members + members