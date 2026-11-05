from pathlib import Path
from setuptools import setup

name="solidcraftbot_ros"
data=[("share/ament_index/resource_index/packages",["resource/"+name]),("share/"+name,["package.xml"])]
for directory in ["launch","config","urdf","meshes"]:
    for parent in sorted({p.parent for p in Path(directory).rglob("*") if p.is_file()}):
        data.append(("share/"+name+"/"+parent.as_posix(),[p.as_posix() for p in sorted(parent.iterdir()) if p.is_file()]))
setup(name=name,version="0.1.0",packages=[name],data_files=data,
      install_requires=["setuptools"],zip_safe=True,maintainer="SolidCraftBot contributors",
      maintainer_email="maintainers@example.invalid",description="UMR mock robot and trajectory client",license="UNLICENSED",
      entry_points={"console_scripts":["run_protocol = solidcraftbot_ros.demo:main"]})
