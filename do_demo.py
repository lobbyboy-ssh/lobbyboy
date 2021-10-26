import time
import os
import digitalocean

droplet = digitalocean.Droplet(
    token=os.getenv("DIGITALOCEAN_TOKEN"),
    name="Example",
    region="sgp1",  # New York 2
    image="ubuntu-20-04-x64",  # Ubuntu 20.04 x64
    size_slug="s-1vcpu-1gb",  # 1GB RAM, 1 vCPU
)
create_time = time.time()
droplet.create()


actions = droplet.get_actions()
print("actions: {}".format(actions))

action1 = actions[0]
check = 0

while 1:
    print("{} action: {}".format(check, action1))
    check += 1
    action1.load()
    time.sleep(1)
    # Once it shows "completed", droplet is up and running
    if action1.status == "completed":
        break

print("total: {}s".format(time.time() - create_time))
