# R80.20 Addressgroup -> Panorama converter tool

## What?
This is a very quick script to convert Checkpoint addresses/address-groups to PAN objects and import into a Panorama.

This supports nested address groups within the checkpoint configuration.

Checkpoint configuration exports from R80 management servers sometimes do not properly resolve member UUIDs. It's 
unclear why this is.

## How

### 1. Get the objects

You can use the show package method:
```bash
$MDS_FWDIR/scripts/web_api_show_package.sh -k <PACKAGE NAME> -d <DOMAIN NAME>
```
the file will be named [package]_objects.json

**untested** you may also be able to use the output of show objects:
```bash
mgmt_cli show objects --format json 
```

### 2. Run the code

```bash
python parser.py [path-to-objects-file].json
```

### Optionally: Enrich with ranges

It is possible that the UUIDs will still not be properly resolved, leading to an incomplete configuration.

There is a checkpoint command that will present all the address objects as IP ranges instead of UUIDS.

```bash
mgmt_cli show groups show-as-ranges "true" --format json
```

If you obtain this JSON you can add it to the parser to autocreate objects matching these ranges.
Addresses created in this manner will be prefixed RR (Recovered Range)

```bash
python parser.py [path-to-objects-file].json --group_ranges [path-to-objects-ranges].json
```
