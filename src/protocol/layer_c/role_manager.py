"""
Role Manager for Dynamic Consumer/PlatoonHead Role Switching.

Handles the logic for determining and transitioning between node roles
based on energy availability and willingness.
"""

from typing import Optional, TYPE_CHECKING

from src.protocol.layer_c.states import NodeRole, ConsumerState, PlatoonHeadState
from src.core.platoon import Platoon
from src.protocol.config import ProtocolConfig

if TYPE_CHECKING:
    from src.protocol.context import MVCCPContext


class RoleManager:
    """
    Manages dynamic role assignment for EVs in the MVCCP protocol.
    
    Role assignment rules are defined in ProtocolConfig:
    - PLATOON_HEAD: shareable_energy >= PH_ENERGY_THRESHOLD_PERCENT * capacity AND willingness >= PH_WILLINGNESS_THRESHOLD
    - CONSUMER: shareable_energy < 0 (can't reach destination) or not meeting PH criteria
    - PLATOON_MEMBER: Already joined a platoon as a member
    - RREH: Predetermined, not dynamically assigned
    """
    
    def __init__(self, context: 'MVCCPContext'):
        """
        Initialize the role manager.
        
        Args:
            context: MVCCP protocol context
        """
        self.context = context
    
    def evaluate_role(self) -> NodeRole:
        """
        Evaluate and return the appropriate role for this node.
        Does NOT change the context's role - call apply_role() for that.
        
        Returns:
            Recommended NodeRole based on current state
        """
        # RREHs are static - never change
        if self.context.is_rreh():
            return NodeRole.RREH
        
        # If already a platoon member (not head), stay as member
        if self.context.is_platoon_member():
            return NodeRole.PLATOON_MEMBER
        
        # Calculate shareable energy
        shareable = self.context.node.shareable_energy()
        threshold = ProtocolConfig.PH_ENERGY_THRESHOLD_PERCENT * self.context.node.battery_capacity_kwh
        willingness = self.context.node.willingness
        
        # Check PH eligibility
        can_be_ph = (
            shareable >= threshold and 
            willingness >= ProtocolConfig.PH_WILLINGNESS_THRESHOLD and
            not self._is_in_platoon_as_member()
        )
        
        if can_be_ph:
            return NodeRole.PLATOON_HEAD
        
        # Otherwise, be a consumer
        return NodeRole.CONSUMER
    
    def apply_role(self, new_role: Optional[NodeRole] = None) -> bool:
        """
        Apply a role change to the context.
        If new_role is None, evaluates the appropriate role first.
        
        Args:
            new_role: Role to apply, or None to auto-evaluate
            
        Returns:
            True if role changed, False if stayed the same
        """
        if new_role is None:
            new_role = self.evaluate_role()
        
        if new_role == self.context.node_role:
            return False
        
        old_role = self.context.node_role
        
        # Handle transition logic
        if old_role == NodeRole.PLATOON_HEAD and new_role != NodeRole.PLATOON_HEAD:
            # Transitioning away from PH - trigger handoff
            self._handle_ph_exit()
        
        if new_role == NodeRole.PLATOON_HEAD:
            # Becoming a PH - initialize platoon
            self._initialize_platoon_head()
        
        # Apply the role change
        self.context.set_role(new_role)
        
        return True
    
    def tick(self, timestamp: float):
        """
        Periodic check for role transitions.
        Called every protocol tick to evaluate if role should change.
        
        Args:
            timestamp: Current simulation time
        """
        # Don't evaluate for RREHs
        if self.context.is_rreh():
            return
        
        # Don't evaluate for platoon members - they stay as members
        if self.context.is_platoon_member():
            # But check if platoon dissolved
            if self.context.current_platoon is None:
                self.context.set_role(NodeRole.CONSUMER)
            return
        
        # Check if current role is still appropriate
        recommended = self.evaluate_role()
        
        if recommended != self.context.node_role:
            # Check for critical state - don't interrupt active sessions
            if self._is_in_active_session():
                return
            
            self.apply_role(recommended)
    
    def _is_in_platoon_as_member(self) -> bool:
        """Check if node is in a platoon as a member (not head)."""
        if self.context.current_platoon is None:
            return False
        return not self.context.current_platoon.is_head(self.context.node)
    
    def _is_in_active_session(self) -> bool:
        """Check if node is in an active charging session."""
        if self.context.is_consumer():
            # Active states where we shouldn't interrupt
            active_states = {
                ConsumerState.WAIT_ACCEPT,
                ConsumerState.WAIT_ACKACK,
                ConsumerState.ALLOCATED,
                ConsumerState.TRAVEL,
                ConsumerState.CHARGE
            }
            return self.context.consumer_state in active_states
        
        if self.context.is_platoon_head():
            # Active states for PH
            active_states = {
                PlatoonHeadState.WAIT_ACK,
                PlatoonHeadState.SEND_ACKACK,
                PlatoonHeadState.COORDINATE
            }
            return self.context.platoon_head_state in active_states
        
        return False
    
    def _initialize_platoon_head(self):
        """Initialize this node as a new platoon head."""
        # Create new platoon with this node as head
        platoon = Platoon(head_node=self.context.node)
        
        # Set common destination to head's destination
        if self.context.node.destination:
            platoon.common_destination = self.context.node.destination
        
        # Link to context
        self.context.current_platoon = platoon
        self.context.current_platoon_id = platoon.platoon_id
        self.context.platoon_members = [self.context.node_id]
        
        # Mark node as leader
        self.context.node.is_leader = True
        self.context.node.platoon = platoon
    
    def _handle_ph_exit(self):
        """Handle transition away from Platoon Head role."""
        platoon = self.context.current_platoon
        
        if platoon is None:
            return
        
        # Try to hand off to best candidate
        candidate = platoon.find_best_handoff_candidate()
        
        if candidate is not None:
            # Hand off to candidate
            platoon.set_head(candidate)
            
            # Update our state
            self.context.node.is_leader = False
            
            # We become a regular member or leave
            if self.context.node.shareable_energy() < 0:
                # Critical - need charge, leave platoon
                platoon.remove_node(self.context.node)
                self.context.current_platoon = None
                self.context.current_platoon_id = None
            else:
                # Stay as member
                pass  # Role will be set to PLATOON_MEMBER or CONSUMER
        else:
            # No candidate - dissolve platoon
            self._dissolve_platoon()
    
    def _dissolve_platoon(self):
        """Dissolve the current platoon."""
        platoon = self.context.current_platoon
        
        if platoon is None:
            return
        
        # Remove all members
        for node in list(platoon.nodes):
            node.platoon = None
            node.is_leader = False
        
        platoon.nodes.clear()
        platoon.node_number = 0
        
        # Clear context
        self.context.current_platoon = None
        self.context.current_platoon_id = None
        self.context.platoon_members = []
    
    def should_handoff(self) -> bool:
        """
        Check if current platoon head should hand off to another member.
        
        Returns:
            True if handoff is recommended
        """
        if not self.context.is_platoon_head():
            return False
        
        platoon = self.context.current_platoon
        if platoon is None:
            return False
        
        # Check if our shareable energy has dropped significantly
        shareable = self.context.node.shareable_energy()
        threshold = self.PH_ENERGY_THRESHOLD * self.context.node.battery_capacity_kwh
        
        # Handoff if we're below 50% of the threshold
        if shareable < threshold * 0.5:
            # Check if there's a better candidate
            candidate = platoon.find_best_handoff_candidate()
            if candidate and candidate.shareable_energy() > shareable * 1.5:
                return True
        
        return False
    
    def perform_handoff(self) -> bool:
        """
        Perform platoon head handoff to best candidate.
        
        Returns:
            True if handoff successful, False otherwise
        """
        if not self.should_handoff():
            return False
        
        platoon = self.context.current_platoon
        if platoon is None:
            return False
        
        candidate = platoon.find_best_handoff_candidate()
        if candidate is None:
            return False
        
        # Perform the handoff
        success = platoon.set_head(candidate)
        
        if success:
            # Update our state
            self.context.node.is_leader = False
            self.context.set_role(NodeRole.PLATOON_MEMBER)
            
            # Note: The new head needs to be notified via message
            # This would be handled by the PlatoonHeadHandler
        
        return success



