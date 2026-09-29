# USB CDC-NCM Networking Architecture

Status: target architecture with an initial installer implementation. See the repository README for current commands and limitations, and `quadra-003-validation.md` for the first hardware results. This document separates facts established by published specifications and kernel documentation from behavior that must be verified with real USB gadget hardware and a Windows host.

## Scope

The deliverable is a reusable device-side installer, not a website or application.
Website hosting, browser-supplied clock synchronization, host internet sharing,
and application firewall policy remain outside this repository's installation scope.
The initial installer supports explicit `rpi-zero` boot configuration and a
`generic` profile for boards whose vendor setup already exposes one UDC. It does
not claim automatic boot configuration for unspecified Radxa models.

The current implementation in `tools/install.py` uses CLI network/board options
and a persistent JSON identity file. The YAML contract below is a future target,
not a currently accepted installer input. Production USB identity configuration,
additional board profiles and Linux/macOS host qualification remain pending.

This repository will provide a reusable Linux device-side USB networking component. It will compose a USB gadget with ConfigFS/libcomposite and the kernel CDC-NCM function, configure the resulting Linux network link, integrate with systemd, and provide diagnostics. It will not contain product identity, board-specific paths, or Windows kernel drivers.

The default gadget is a single USB configuration containing one `ncm` function.
The optional `--gadget ncm-storage` mode adds a read-only `mass_storage` function
to that same configuration. Its FAT image contains `START-HERE.html`; the backing
image is generated before attachment and replaced only after gadget teardown.
Composite host/controller qualification is pending. RNDIS is not implemented.

## Target data path

```text
Embedded Linux network stack
  -> Linux NCM net device (name discovered at runtime)
  -> usb_f_ncm / libcomposite
  -> USB Device Controller
  -> USB cable
  -> Windows USB bus and class binding
  -> UsbNcm.sys, where supported and selected
  -> Windows network adapter
```

The setup program owns orchestration, not packet framing. NCM framing, control requests, descriptors, endpoint handling, and link state are delegated to the Linux kernel function.

## Evidence and verification status

### Established by authoritative documentation

- Linux ConfigFS requires `CONFIGFS_FS`; `USB_LIBCOMPOSITE` selects it in normal kernel configurations. The gadget is created below the ConfigFS `usb_gadget` directory.
- A gadget requires `idVendor`, `idProduct`, and a language-specific manufacturer, product, and serial-number string directory.
- A function is created as `functions/<type>.<instance>` and linked into a configuration. The gadget is enabled by writing a name from `/sys/class/udc` to `UDC`; disabling writes an empty value.
- The Linux NCM function is `usb_f_ncm.ko`, created as `functions/ncm.<instance>`. Kernel documentation lists `ifname`, `qmult`, `host_addr`, `dev_addr`, and `max_segment_size` as function attributes. The documented defaults include randomly selected MAC addresses, so production configuration must set both addresses explicitly.
- Linux documents the NCM function as a CDC-NCM networking function and provides a basic two-sided ping test.
- Windows generates standard USB identifiers from device and interface descriptors. VID/PID and interface identity therefore affect device matching and adapter persistence.
- An INF is a driver-package installation mechanism. It must not be used by this project to replace an inbox class driver automatically.

Sources:

- [Linux USB gadget ConfigFS](https://docs.kernel.org/usb/gadget_configfs.html)
- [Linux gadget function testing, NCM section](https://docs.kernel.org/usb/gadget-testing.html#ncm-function)
- [Linux ConfigFS USB gadget ABI](https://docs.kernel.org/admin-guide/abi-testing.html#abi-config-usb-gadget-gadget-functions-ncm-name)
- [Linux CDC-NCM network ABI](https://docs.kernel.org/admin-guide/abi-testing.html#abi-sys-class-net-iface-cdc-ncm)
- [Microsoft USB device identifiers](https://learn.microsoft.com/en-us/windows-hardware/drivers/install/identifiers-for-usb-devices)
- [Microsoft INF overview](https://learn.microsoft.com/en-us/windows-hardware/drivers/install/overview-of-inf-files)

### Not established by the sources reviewed

The reviewed Microsoft documentation did not provide a stable public compatibility matrix for `UsbNcm.sys`, its exact first supported Windows release, the complete matching predicates it uses for CDC-NCM, or whether all Windows 10 and Windows 11 servicing builds behave identically. The URL often cited as a Microsoft USB-NCM page currently returns 404. These are release-gating test items, not assumptions in the implementation.

The following must be captured from real hosts with USB descriptor dumps, Device Manager/PowerShell, SetupAPI event logs, and packet tests:

- Windows version/build and architecture matrix for inbox `UsbNcm.sys`.
- Whether the inbox driver binds to the Linux-generated descriptors without an INF.
- Whether an IAD is required by each tested Windows build for the CDC control/data pair.
- Whether the Linux-generated NCM functional descriptors and endpoint choices are accepted at full/high/super speed.
- Adapter identity behavior after reconnect, gadget recreation, serial-number changes, and multiple identical devices.
- Composite configurations containing NCM plus other functions.
- NCM control negotiation, NTB format/size interoperability, suspend/resume, and reconnect recovery.

## USB descriptor contract

The implementation will use the descriptors emitted by the Linux `usb_f_ncm` function rather than hand-building class descriptors. Descriptor validation will inspect the emitted descriptor tree and compare it with the standards contract.

The expected CDC-NCM function shape is:

- CDC communication/control interface: USB class `0x02` (Communications and CDC Control), subclass `0x0d` (NCM), protocol `0x00` unless the kernel function specifies otherwise.
- CDC data interface: class `0x0a` (CDC Data), subclass `0x00`, protocol `0x00`.
- CDC control endpoint: interrupt IN.
- CDC data endpoints: bulk IN and bulk OUT.
- CDC functional descriptors: Interface Association/association metadata as emitted by the kernel where applicable, CDC Union, CDC Ethernet Networking, and CDC NCM functional descriptor identifying the NCM version and capabilities.
- One configuration with the control and data interfaces associated as one function.

The class/subclass/protocol values above are the expected CDC values from the USB CDC model and must be confirmed in the actual Linux descriptor dump. Exact descriptor lengths, interface numbers, endpoint addresses, packet sizes, `wMaxPacketSize`, NCM version, NTB parameters, and IAD presence are kernel- and speed-dependent and must not be hard-coded in tests as universal values.

An IAD is part of the validation target for a multi-interface CDC function, but this design does not claim that an IAD alone guarantees Windows binding. The validation tool will report both presence and placement relative to the control/data interfaces.

Microsoft OS descriptors are not required by the CDC-NCM standard and are not assumed by this design. They may be tested only as an isolated compatibility experiment if a Windows build demonstrates a concrete need. They must never advertise RNDIS or install a custom driver implicitly.

## Identity model

All identity values are configuration inputs and are written before binding:

- VID and PID: assigned by the product owner or USB-IF process. Example values are placeholders and are rejected by production validation unless an explicit development mode is enabled.
- Manufacturer and product strings: product configuration, not source constants.
- Serial number: stable and unique per physical unit. Prefer a manufacturing-provisioned opaque identifier or a stable hardware identifier transformed with a product-controlled keyed derivation. Do not expose raw sensitive hardware identifiers and do not generate a new random value at boot.
- Device MAC and host MAC: stable, locally administered unicast addresses. Prefer manufacturing-provisioned addresses; otherwise derive them deterministically from an opaque unit identity and a product allocation prefix. Never use the Linux NCM defaults in production.

A stable serial number, stable VID/PID, stable interface layout, and stable MAC addresses give Windows the best opportunity to retain one adapter identity across reconnects. Windows persistence is still host-state behavior and is tested, not promised by the device.

Multiple devices connected to one Windows host require unique serial numbers and unique MAC addresses. Products must allocate identities without collisions across the deployed population.

## Network model

The default profile is device-served DHCP on a private IPv4 subnet, with a fixed device address and a small address pool that leases the host address. This requires no manual Windows address configuration and gives deterministic device reachability. The DHCP server is a replaceable platform dependency and must be explicitly enabled only when available.

Supported alternatives:

| Mode | Windows configuration | Determinism | Recommendation |
| --- | --- | --- | --- |
| Device DHCP | Usually none | High with a fixed pool/lease policy | Default |
| Static IPv4 | Requires host configuration or provisioning | Highest | Fallback for controlled systems |
| IPv4 link-local | Usually none | Low; address can change | Diagnostics/fallback only |
| IPv6 link-local | Usually none | Address discovery required | Optional, not the only path |
| DHCP plus IPv6 link-local | Usually none | Good | Optional combined profile |

The implementation will configure the device address after the NCM net device appears, using udev/systemd device events or polling with a bounded timeout. It will never assume `usb0`, `ncm0`, or another fixed interface name. If a configured `ifname` pattern is supported by the installed kernel, it is treated as a hint; the actual resulting interface is discovered from the function's sysfs relationship.

IPv6 defaults to disabled for the first implementation profile unless explicitly enabled. If enabled, link-local IPv6 is allowed; global addressing, router advertisements, and DHCPv6 are outside the initial scope.

## Lifecycle and recovery

Start is an ordered transaction:

1. Load or request `libcomposite` and `usb_f_ncm`.
2. Verify ConfigFS is mounted or mount it at the configured mount point.
3. Verify at least one UDC exists and select the configured UDC or the sole available UDC.
4. Validate all configuration, including identity uniqueness requirements that can be checked locally.
5. Create or reconcile the gadget, strings, configuration, and NCM function.
6. Set stable MAC addresses and other function attributes before binding.
7. Bind to the UDC only after the descriptor tree is complete.
8. Discover the created network interface, bring it up, and apply the selected network profile.

Stop unbinds the UDC first, removes configuration links, removes function instances, and removes only the gadget-owned directories. Cleanup is best-effort but logged; partial creation is rolled back on failure. Repeated start/stop must converge to the same state.

Reconnects and gadget recreation are treated as independent events. The network configuration layer watches for the function's net device and reapplies link state/addressing without relying on a device-interface name. Systemd ordering will cover local filesystems, ConfigFS, UDC availability, and the network service, while runtime recovery handles later USB cable and host events.

## Composite-device policy

The initial implementation supports one NCM function in one configuration. Composite support is a future milestone because interface numbering, IAD grouping, Windows matching, power budget, and function-driver interactions require host testing. Adding serial, mass-storage, or RNDIS functions must not be treated as a harmless configuration change.

## Configuration contract

The canonical format is YAML, parsed and validated before any ConfigFS mutation. A complete example is in `config/example.yaml`.

Required groups and keys:

```yaml
usb:
  gadget_name: generic-ncm
  udc: auto
  vid: 0x1d6b
  pid: 0x0104
  manufacturer: Example Manufacturer
  product: Example CDC-NCM Network
  serial: DEV-00000001
  language: 0x409
  configuration: CDC-NCM
  max_power_ma: 250
network:
  device_mac: 02:00:00:00:00:01
  host_mac: 02:00:00:00:00:02
  subnet: 192.0.2.0/30
  device_address: 192.0.2.1
  dhcp:
    mode: server
    host_address: 192.0.2.2
  ipv6:
    mode: disabled
```

`0x1d6b:0x0104` is a development/example identity only and is unsuitable for production. Production validation will require an approved VID/PID policy. The schema will also support `udc: auto`, `dhcp.mode: disabled|server`, `ipv6.mode: disabled|link-local`, and an optional NCM `max_segment_size`/`qmult` section without changing the identity contract.

## Diagnostics and test boundary

The Linux diagnostic tool will report kernel release/configuration, ConfigFS mount state, available UDCs, gadget tree, bound UDC, NCM function attributes, discovered net device, MACs, carrier, addresses, routes, and relevant journal entries.

The Windows PowerShell tool will report USB VID/PID/serial, PnP status, driver and service path, network adapter, addresses/routes, and connectivity. It will explicitly say whether the selected service image is `UsbNcm.sys`; it will not install a driver.

CI can test YAML/schema validation, deterministic identity derivation, descriptor parsing against captured fixtures, transaction rollback using a fake ConfigFS tree, and idempotency. Real UDC creation, electrical reconnect behavior, Windows binding, adapter persistence, and throughput require a hardware-in-the-loop matrix.

## Risks and decisions

- **Inbox driver availability:** no authoritative current Microsoft matrix was found. Mitigation: publish a tested Windows build matrix and fail documentation claims closed until tested.
- **Driver binding:** CDC compliance does not guarantee a particular Windows service selection. Mitigation: minimal single-function descriptors, no OS-descriptor hacks, capture SetupAPI evidence.
- **Kernel variation:** ConfigFS attributes and generated descriptors vary by kernel version/configuration. Mitigation: runtime capability checks and descriptor fixtures per supported kernel family.
- **Random identity defaults:** Linux NCM defaults can change across boots. Mitigation: always write configured addresses and stable serial before UDC binding.
- **Network interface naming:** names are dynamic. Mitigation: discover via sysfs/udev and configure by device relationship.
- **DHCP dependency:** a device DHCP server may not exist in a minimal image. Mitigation: static IPv4 profile and optional link-local fallback.
- **Windows adapter duplication:** changed serials or identity/layout changes can create new adapters. Mitigation: identity provisioning policy and reconnect/reboot tests.
- **Composite compatibility:** extra functions can alter matching and interface association. Mitigation: single NCM default and separate qualification milestone.
- **VID/PID ownership:** example IDs cannot ship. Mitigation: explicit production validation and documentation gate.

## Open validation questions

Before implementation is declared production-ready, test and record:

1. Which Windows 10 and Windows 11 builds bind the captured Linux descriptors to `UsbNcm.sys`?
2. Does any supported build require an INF for a generic VID/PID, and can that INF remain metadata-only without replacing the inbox driver?
3. Does the driver accept the kernel's NCM 1.0 descriptor and negotiated NTB parameters at each USB speed?
4. Does a stable serial plus stable MAC preserve the same Windows adapter across all lifecycle events?
5. What composite layouts, if any, remain inbox-compatible?

Until answered, the project promises standards-compliant Linux CDC-NCM generation and a testable Windows compatibility target, not universal Windows recognition.
