import time
import os
import digitalocean

droplet = digitalocean.Droplet.get_object(
    api_token=os.getenv("DIGITALOCEAN_TOKEN"),
    droplet_id="269903147",
)
create_time = time.time()
result = droplet.destroy()
print(result)
print("time: {}".format(time.time() - create_time))
