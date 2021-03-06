"""
Spoke 'Junction' of Mission Control.
Handles Telnet clients issuing commands for direct service control.
Functions should encompass server -> device interactions.
Direct user interface is expected to be less frequent.
"""
import logging
import os
import pickle
import socket
import telnetlib
import threading

from miniboa import TelnetServer

# Modify the following with newly implemented tasks #
from spoke.tasks import morse, printer, light, lamp

ALL_SERVICES = {
    'morse': morse,
    'print': printer,
    'light': light,
    'lamp': lamp,
}
#####################################################

IDLE_TIMEOUT = 30
CLIENTS = []
SERVICES = {}
RUN = True
WELCOME = "Mission Control Junction at your service.\n$junction > "

"""
Server internal operations
"""


def on_connect(client):
    logging.info("Opened connection to " + str(client.addrport()))
    CLIENTS.append(client)
    client.okay = okay
    client.error = error
    client.tell = tell
    client.send(WELCOME)


def on_disconnect(client):
    logging.info("Closed connection to " + str(client.addrport()))
    CLIENTS.remove(client)


def read_services():
    try:
        with open('save/services.pkl', 'rb') as file:
            global SERVICES
            service_names = pickle.load(file)
            for service in service_names:
                mapped = ALL_SERVICES[service]
                if mapped is not None:
                    SERVICES[service] = ALL_SERVICES[service]
                else:
                    logging.error("Saved service '" + service + "' not available.")
            # SERVICES = pickle.load(file)
    except FileNotFoundError:
        logging.info("No saved services found.")


def verify_path():
    if not os.path.exists('save'):
        os.makedirs('save')


def save_services():
    logging.info("Saving services to file.")
    verify_path()
    with open('save/services.pkl', 'wb') as output:
        pickle.dump(list(SERVICES.keys()), output)


def kick_idle():
    for client in CLIENTS:
        if client.idle() > IDLE_TIMEOUT:
            logging.info("Kicked for idle: " + str(client.addrport()))
            close(client, None)


def tell_all(message):
    for client in CLIENTS:
        client.send(message + "\n")


def tell(client, message):
    client.send(message + "\n")


def error(client):
    tell(client, "ERROR")


def okay(client):
    tell(client, "OKAY")


def stop(client, args):
    logging.info("Client " + str(client.addrport()) + " requested stop service.")
    save_services()
    global RUN
    RUN = False


def process():
    for client in CLIENTS:
        if client.active and client.cmd_ready:
            thread = threading.Thread(target=interpret, args=(client, client.get_command()))
            thread.start()


def interpret(client, command: str):
    logging.debug(str(client.addrport()) + " sent " + command)
    components = command.split()
    if len(components) > 0:
        command = components[0].lower()
        args = components[1:]

        call = COMMANDS.get(command)
        if call is None:
            error(client)
            tell(client, "Command '" + command + "' not found.")
        else:
            call(client, args)
    else:
        client.send("")
    client.send("$junction > ")


"""
Client addressable commands
"""


def hlp(client, args):
    if len(args) == 0:
        tell(client, "Available commands: " + ', '.join(map(str, COMMANDS.keys())))
        tell(client, "For details, use help <command>.")
    else:
        help_text = COMMANDS_HELP.get(args[0])
        if help_text is None:
            error(client)
            tell(client, "Command '" + args[0] + "' not found.")
        else:
            tell(client, args[0] + ": " + help_text)


def close(client, args):
    client.active = False
    client.deactivate()


def service(client, args):
    if len(args) < 1:
        tell(client, COMMANDS_HELP.get('service'))
        return
    target = str(args[0])
    if target not in SERVICES.keys():
        error(client)
        tell(client, "Service '" + target + "' not available.")
    else:
        call = SERVICES.get(target).do
        if len(args) > 1:
            try:
                call(client, args[1:])
            except TypeError:
                error(client)
                tell(client, "Invalid number of arguments.")
        else:
            try:
                call(client)
            except TypeError:
                error(client)
                tell(client, "Invalid number of arguments.")


def discover(client, args):
    build = {}
    for svc in SERVICES.keys():
        build[svc] = SERVICES.get(svc).discover()
    tell(client, str(build))


def status(client, args):
    if len(args) < 1:
        tell(client, COMMANDS_HELP.get('status'))
        return
    target = str(args[0])
    target_call = SERVICES.get(target)

    if target_call is not None:
        try:
            tell(client, target_call.status())
        except AttributeError:
            error(client)
            tell(client, "'" + target + "' does not support status.")
    else:
        error(client)
        tell(client, "'" + target + "' not recognized as a service.")


def save(client, args):
    save_services()
    okay(client)


def enable(client, args):
    if len(args) < 1:
        tell(client, COMMANDS_HELP.get('enable'))
        return
    target = str(args[0])
    if target not in ALL_SERVICES.keys():
        error(client)
        tell(client, "Service '" + target + "' not available to enable.")
    else:
        SERVICES[target] = ALL_SERVICES.get(target)
        okay(client)


def disable(client, args):
    if len(args) < 1:
        tell(client, COMMANDS_HELP.get('disable'))
        return
    target = str(args[0])
    if target not in SERVICES.keys():
        error(client)
        tell(client, "Service '" + target + "' not available to disable.")
    else:
        SERVICES.pop(target)
        okay(client)


def tell_next(client, args):
    # Intended to allow 'pivoting' through junctions
    # Currently causes server freeze on both sides talking to reception!
    # Disabled for now...
    if len(args) < 3:
        tell(client, COMMANDS_HELP.get('disable'))
        return
    target_ip = str(args[0])
    target_port = str(args[1])
    target_args = str(args[2:])

    try:
        tn = telnetlib.Telnet(target_ip, target_port, timeout=5)
        tn.read_until("> ".encode('utf-8'))  # Ignore welcome message
        tn.write((' '.join(map(str, target_args)) + "\r\n").encode('utf-8'))
        tn.read_very_eager()
        tn.close()
        okay(client)
    except (ConnectionAbortedError, ConnectionRefusedError, ConnectionAbortedError, ConnectionError,
            ConnectionResetError, TimeoutError, socket.timeout, EOFError) as e:
        error(client)
        print(e)
        tell(client, "Unable to reach " + target_ip)
        logging.error("Unable to reach " + target_ip)


"""
Definition of commands
"""
COMMANDS = {
    'help': hlp,
    'end': close,
    'exit': close,
    'stop': stop,
    'service': service,
    'discover': discover,
    'status': status,
    'enable': enable,
    'disable': disable,
    'save': save,
}

COMMANDS_HELP = {
    'help': "... you've got this one.",
    'end': "Terminates Telnet session.",
    'exit': "Terminates Telnet session.",
    'stop': "Stops the junction service, closing all connections.",
    'service': "Perform a service command.\nservice <name> <*action> <*args>",
    'discover': "Return a formatted list of services and actions.",
    'status': "Return the status of a service.\nstatus <service>",
    'enable': "Enable a service on the device.\nenable <name> <*args>",
    'disable': "Disable a service on the device.\ndisable <name> <*args>",
    'save': "Save enabled services to local server files for recovery after restart."
}

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    telnet_server = TelnetServer(
        port=9092,
        address='',
        on_connect=on_connect,
        on_disconnect=on_disconnect,
        timeout=0.5)

    logging.info("Listening on " + str(telnet_server.port))

    read_services()

    while RUN:
        telnet_server.poll()
        process()
        kick_idle()

    logging.info("Shutting down.")
